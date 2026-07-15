"""Explicit, idempotent installation of ambient integrations."""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from .errors import AxiError


def setup_hooks(target: str) -> dict[str, Any]:
    command = _command()
    selected = ("claude", "codex", "opencode") if target == "all" else (target,)
    changed: list[str] = []
    for item in selected:
        if item == "claude":
            path = Path.home() / ".claude" / "settings.json"
            if _merge_hook(path, "hooks", "SessionStart", command):
                changed.append(item)
        elif item == "codex":
            path = Path.home() / ".codex" / "hooks.json"
            hook_changed = _merge_hook(path, "hooks", "SessionStart", command)
            config_changed = _enable_codex_hooks(Path.home() / ".codex" / "config.toml")
            if hook_changed or config_changed:
                changed.append(item)
        else:
            path = Path.home() / ".config" / "opencode" / "plugins" / "codex-axi.js"
            content = _opencode_plugin(command)
            if _write_if_changed(path, content):
                changed.append(item)
    return {
        "setup": {
            "targets": list(selected),
            "changed": changed,
            "status": "updated" if changed else "no_op",
        }
    }


def _merge_hook(path: Path, root: str, event: str, command: str) -> bool:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        data = {}
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
    hook = {"matcher": "", "hooks": [{"type": "command", "command": command}]}
    existing = data.setdefault(root, {}).setdefault(event, [])
    filtered = [entry for entry in existing if "codex-axi" not in json.dumps(entry)]
    filtered.append(hook)
    data[root][event] = filtered
    return _write_if_changed(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


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
    if re.search(r"(?m)^hooks[ \t]*=[ \t]*true[ \t]*$", content):
        return False
    disabled = re.search(r"(?m)^hooks[ \t]*=[ \t]*false[ \t]*$", content)
    if disabled:
        content = content[: disabled.start()] + "hooks = true" + content[disabled.end() :]
        return _write_if_changed(path, content)
    match = re.search(r"(?m)^\[features\]\s*$", content)
    if match:
        insert = match.end()
        content = content[:insert] + "\nhooks = true" + content[insert:]
    else:
        content = content.rstrip() + "\n\n[features]\nhooks = true\n"
    return _write_if_changed(path, content)


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
