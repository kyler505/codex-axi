"""Explicit, idempotent installation of ambient integrations."""

from __future__ import annotations

import json
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import AxiError

ADAPTER_VERSIONS = {"claude": 1, "codex": 1, "opencode": 1}


@dataclass(frozen=True)
class IntegrationAdapter:
    target: str
    contract_version: int

    @property
    def path(self) -> Path:
        if self.target == "claude":
            return Path.home() / ".claude" / "settings.json"
        if self.target == "codex":
            return Path.home() / ".codex" / "hooks.json"
        return Path.home() / ".config" / "opencode" / "plugins" / "codex-axi.js"

    def validate(self, command: str) -> str:
        if self.target == "opencode":
            content = _opencode_plugin(command)
            return (
                "current"
                if self.path.exists() and self.path.read_text() == content
                else ("drifted" if self.path.exists() else "missing")
            )
        status = _hook_status(self.path, command)
        if self.target == "codex":
            _validate_codex_config(Path.home() / ".codex" / "config.toml")
        return status

    def install(self, command: str) -> bool:
        status = self.validate(command)
        if self.target == "opencode":
            if status == "drifted":
                self.validate_remove(command)
            return _write_if_changed(self.path, _opencode_plugin(command))
        hook_changed = _merge_hook(self.path, "hooks", "SessionStart", command)
        if self.target == "codex":
            return _enable_codex_hooks(Path.home() / ".codex" / "config.toml") or hook_changed
        return hook_changed

    def validate_remove(self, command: str) -> None:
        if self.target != "opencode" or not self.path.exists():
            return
        content = self.path.read_text()
        match = re.search(r"(?m)^const command = (.+);$", content)
        try:
            installed_command = json.loads(match.group(1)) if match else None
        except json.JSONDecodeError:
            installed_command = None
        if not isinstance(installed_command, str) or content != _opencode_plugin(installed_command):
            raise AxiError(
                "integration_drift",
                f"Refusing to remove modified OpenCode plugin at {self.path}.",
                "Review the file and remove it manually if those changes are no longer needed.",
            )

    def remove(self, command: str) -> bool:
        self.validate_remove(command)
        if self.target == "opencode":
            if not self.path.exists():
                return False
            self.path.unlink()
            return True
        return _remove_hook(self.path, "hooks", "SessionStart")


ADAPTERS = {name: IntegrationAdapter(name, version) for name, version in ADAPTER_VERSIONS.items()}


def setup_hooks(target: str, *, check: bool = False, remove: bool = False) -> dict[str, Any]:
    command = _command()
    selected = ("claude", "codex", "opencode") if target == "all" else (target,)
    changed: list[str] = []
    adapters: list[dict[str, Any]] = []
    current = {item: ADAPTERS[item].validate(command) for item in selected}
    if remove:
        for item in selected:
            ADAPTERS[item].validate_remove(command)
    elif not check and "opencode" in selected and current["opencode"] == "drifted":
        ADAPTERS["opencode"].validate_remove(command)
    for item in selected:
        adapter = ADAPTERS[item]
        state = current[item]
        if check:
            pass
        elif remove:
            if adapter.remove(command):
                changed.append(item)
        else:
            if adapter.install(command):
                changed.append(item)
        if not check and not remove:
            state = "current"
        adapters.append(
            {
                "target": item,
                "contract_version": adapter.contract_version,
                "status": "removed" if remove and item in changed else state,
            }
        )
    return {
        "setup": {
            "targets": list(selected),
            "changed": changed,
            "status": "checked" if check else ("updated" if changed else "no_op"),
            "adapters": adapters,
        }
    }


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as error:
        raise AxiError(
            "invalid_integration_config",
            f"Cannot update malformed JSON configuration at {path}.",
            f"Repair `{path}` and rerun setup; the existing file was not changed.",
        ) from error
    if not isinstance(data, dict):
        raise AxiError(
            "invalid_integration_config",
            f"Expected a JSON object at {path}.",
            f"Repair `{path}` and rerun setup; the existing file was not changed.",
        )
    return data


def _hook_status(path: Path, command: str) -> str:
    data = _read_json_object(path)
    entries = _hook_entries(data, path, "hooks", "SessionStart") if data else []
    managed = [entry for entry in entries if _managed_hook_command(entry) is not None]
    if not managed:
        return "missing"
    current = any(_managed_hook_command(entry) == command for entry in managed)
    return "current" if current else "drifted"


def _merge_hook(path: Path, root: str, event: str, command: str) -> bool:
    data = _read_json_object(path)
    hook = {"matcher": "", "hooks": [{"type": "command", "command": command}]}
    existing = _hook_entries(data, path, root, event, create=True)
    filtered = [entry for entry in existing if _managed_hook_command(entry) is None]
    filtered.append(hook)
    data[root][event] = filtered
    return _write_if_changed(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def _remove_hook(path: Path, root: str, event: str) -> bool:
    data = _read_json_object(path)
    if not data:
        return False
    existing = _hook_entries(data, path, root, event)
    filtered = [entry for entry in existing if _managed_hook_command(entry) is None]
    if filtered == existing:
        return False
    data[root][event] = filtered
    return _write_if_changed(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def _hook_entries(
    data: dict[str, Any], path: Path, root: str, event: str, *, create: bool = False
) -> list[Any]:
    container = data.setdefault(root, {}) if create else data.get(root, {})
    if not isinstance(container, dict):
        raise AxiError(
            "invalid_integration_config",
            f"Expected `{root}` to be an object at {path}.",
            f"Repair `{path}` and rerun setup; the existing file was not changed.",
        )
    entries = container.setdefault(event, []) if create else container.get(event, [])
    if not isinstance(entries, list):
        raise AxiError(
            "invalid_integration_config",
            f"Expected `{root}.{event}` to be an array at {path}.",
            f"Repair `{path}` and rerun setup; the existing file was not changed.",
        )
    return entries


def _managed_hook_command(entry: Any) -> str | None:
    if not isinstance(entry, dict) or set(entry) != {"matcher", "hooks"}:
        return None
    hooks = entry.get("hooks")
    if entry.get("matcher") != "" or not isinstance(hooks, list) or len(hooks) != 1:
        return None
    hook = hooks[0]
    if not isinstance(hook, dict) or set(hook) != {"type", "command"}:
        return None
    command = hook.get("command")
    if hook.get("type") != "command" or not isinstance(command, str):
        return None
    executable = Path(command).name.lower()
    return command if executable in {"codex-axi", "codex-axi.exe"} else None


def integration_capability_statuses() -> dict[str, str]:
    """Return read-only host adapter status without making doctor fail on user config drift."""

    command = _command()
    statuses: dict[str, str] = {}
    for name, adapter in ADAPTERS.items():
        try:
            state = adapter.validate(command)
        except (AxiError, OSError):
            statuses[name] = "degraded"
        else:
            statuses[name] = {
                "current": "supported",
                "drifted": "degraded",
                "missing": "unknown",
            }[state]
    return statuses


def _command() -> str:
    resolved = shutil.which("codex-axi")
    current = str(Path(sys.argv[0]).resolve())
    return "codex-axi" if resolved and Path(resolved).resolve() == Path(current) else current


def _write_if_changed(path: Path, content: str) -> bool:
    try:
        if path.read_text() == content:
            return False
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return True


def _enable_codex_hooks(path: Path) -> bool:
    try:
        content = path.read_text()
    except FileNotFoundError:
        content = ""
    if content:
        _parse_toml(path, content)
    section = re.search(r"(?m)^\[features\][ \t]*(?:#.*)?$", content)
    section_end = (
        re.search(r"(?m)^\[[^\n]+\][ \t]*(?:#.*)?$", content[section.end() :])
        if section
        else None
    )
    start = section.end() if section else 0
    end = start + section_end.start() if section and section_end else len(content)
    features = content[start:end] if section else ""
    if re.search(r"(?m)^hooks[ \t]*=[ \t]*true[ \t]*(?:#.*)?$", features):
        return False
    disabled = re.search(r"(?m)^hooks[ \t]*=[ \t]*false[ \t]*(?:#.*)?$", features)
    if disabled:
        absolute_start = start + disabled.start()
        absolute_end = start + disabled.end()
        content = content[:absolute_start] + "hooks = true" + content[absolute_end:]
        return _write_if_changed(path, content)
    if section:
        insert = section.end()
        content = content[:insert] + "\nhooks = true" + content[insert:]
    else:
        prefix = content.rstrip()
        content = (prefix + "\n\n" if prefix else "") + "[features]\nhooks = true\n"
    return _write_if_changed(path, content)


def _validate_codex_config(path: Path) -> None:
    try:
        content = path.read_text()
    except FileNotFoundError:
        return
    _parse_toml(path, content)


def _parse_toml(path: Path, content: str) -> None:
    try:
        try:
            import tomllib
        except ImportError:  # pragma: no cover - Python 3.10
            import tomli as tomllib
        tomllib.loads(content)
    except Exception as error:
        raise AxiError(
            "invalid_integration_config",
            f"Cannot update malformed TOML configuration at {path}.",
            f"Repair `{path}` and rerun setup; the existing file was not changed.",
        ) from error


def _opencode_plugin(command: str) -> str:
    return _OPENCODE_TEMPLATE.replace("__COMMAND__", json.dumps(command))


_OPENCODE_TEMPLATE = """// codex-axi managed ambient context plugin
import { spawn } from "node:child_process";

const command = __COMMAND__;
const timeoutMs = 10000;

function dashboard(cwd) {
  return new Promise((resolve) => {
    const child = spawn(command, [], {
      cwd: typeof cwd === "string" && cwd.length > 0 ? cwd : process.cwd(),
      env: process.env,
      shell: false,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.kill("SIGTERM");
      resolve("error: codex-axi dashboard timed out");
    }, timeoutMs);
    child.stdout?.setEncoding("utf-8");
    child.stderr?.setEncoding("utf-8");
    child.stdout?.on("data", (chunk) => { stdout += chunk; });
    child.stderr?.on("data", (chunk) => { stderr += chunk; });
    child.on("error", (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve("error: codex-axi dashboard failed: " + error.message);
    });
    child.on("close", (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(code === 0 ? stdout.trim() : "error: " + (stderr || stdout).trim());
    });
  });
}

export const CodexAxiAmbientContextPlugin = async ({ directory }) => {
  const cache = new Map();
  return {
    "experimental.chat.system.transform": async (input, output) => {
      const session = input.sessionID ?? "__global__";
      if (!cache.has(session)) cache.set(session, await dashboard(directory));
      const value = cache.get(session);
      if (value) output.system.push("## AXI ambient context: codex-axi\\n" + value);
    },
  };
};
"""
