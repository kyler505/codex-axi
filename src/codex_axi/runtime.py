"""Runtime discovery and the official SDK proxy connection path."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from typing import Callable, Sequence

from .errors import AxiError, translate_runtime_error

SUPPORTED_CODEX = ">=0.144.0,<0.145.0"


@dataclass(frozen=True)
class RuntimeCapabilities:
    codex_path: str | None
    cli_version: str | None
    proxy_available: bool
    daemon_available: bool
    daemon_state: str
    detail: str | None = None
    sdk_version: str | None = None
    supported_codex: str = SUPPORTED_CODEX

    def document(self) -> dict[str, object]:
        return asdict(self)


Run = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=False, timeout=10)


def _proxy_handshake(codex_path: str) -> bool:
    """A PID/version is insufficient: require a JSON-RPC response via proxy."""
    request = (
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":'
        '{"clientInfo":{"name":"codex-axi","version":"0.1.0"},"capabilities":{}}}\n'
    )
    try:
        result = subprocess.run(
            (codex_path, "app-server", "proxy"),
            input=request,
            text=True,
            capture_output=True,
            check=False,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and '"id":1' in result.stdout and '"result"' in result.stdout


def probe_runtime(
    run: Run = _run, which: Callable[[str], str | None] = shutil.which
) -> RuntimeCapabilities:
    try:
        sdk_version = package_version("openai-codex")
    except PackageNotFoundError:
        sdk_version = None
    codex_path = which("codex")
    if codex_path is None:
        return RuntimeCapabilities(
            None, None, False, False, "unavailable", "`codex` is not on PATH", sdk_version
        )
    version = run((codex_path, "--version"))
    version_text = version.stdout.strip() if version.returncode == 0 else None
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", version_text or "")
    if match and (int(match.group(1)), int(match.group(2))) != (0, 144):
        return RuntimeCapabilities(
            codex_path,
            version_text,
            False,
            False,
            "version-mismatched",
            f"supported Codex range is {SUPPORTED_CODEX}",
            sdk_version,
        )
    proxy = run((codex_path, "app-server", "proxy", "--help"))
    daemon = run((codex_path, "app-server", "daemon", "--help"))
    if not (proxy.returncode == 0 and daemon.returncode == 0):
        return RuntimeCapabilities(
            codex_path,
            version_text,
            proxy.returncode == 0,
            daemon.returncode == 0,
            "unavailable",
            None,
            sdk_version,
        )
    status = run((codex_path, "app-server", "daemon", "version"))
    if status.returncode == 0:
        try:
            versions = json.loads(status.stdout)
            if versions.get("cliVersion") != versions.get("appServerVersion"):
                return RuntimeCapabilities(
                    codex_path,
                    version_text,
                    True,
                    True,
                    "version-mismatched",
                    "daemon and app-server versions do not match",
                    sdk_version,
                )
        except json.JSONDecodeError:
            pass
        if run is _run and not _proxy_handshake(codex_path):
            return RuntimeCapabilities(
                codex_path,
                version_text,
                True,
                True,
                "unhealthy",
                "app-server proxy did not complete the initialize handshake",
                sdk_version,
            )
        return RuntimeCapabilities(
            codex_path,
            version_text,
            True,
            True,
            "healthy",
            "protocol handshake completed",
            sdk_version,
        )
    raw_detail = (status.stderr or status.stdout).strip()
    lowered = raw_detail.lower()
    if "starting" in lowered:
        state = "starting"
    elif "no such file" in lowered or "failed to connect" in lowered:
        state = "stopped"
    else:
        state = "unhealthy"
    detail = {
        "starting": "managed daemon is starting",
        "stopped": "managed daemon is not running",
        "unhealthy": "managed daemon health check failed",
    }[state]
    return RuntimeCapabilities(codex_path, version_text, True, True, state, detail, sdk_version)


def open_connection(capabilities: RuntimeCapabilities, *, require_shared: bool = False):
    """Create the SDK client, preferring the managed proxy when supported."""
    if not capabilities.codex_path:
        raise AxiError(
            "codex_missing",
            "Codex CLI is unavailable.",
            "Install Codex, then run `codex-axi doctor`.",
        )
    if require_shared and capabilities.daemon_state != "healthy":
        raise AxiError(
            "shared_runtime_required",
            "This operation requires the managed Codex daemon.",
            "Update Codex and run `codex app-server daemon start`.",
        )
    try:
        from openai_codex import Codex, CodexConfig

        if capabilities.proxy_available and capabilities.daemon_state == "healthy":
            config = CodexConfig(
                codex_bin=capabilities.codex_path,
                launch_args_override=(capabilities.codex_path, "app-server", "proxy"),
            )
        else:
            config = CodexConfig(codex_bin=capabilities.codex_path)
        return Codex(config)
    except AxiError:
        raise
    except Exception as error:
        raise translate_runtime_error(error) from error


open_proxy_connection = open_connection


def read_thread_compat(client, thread_id: str, *, include_turns: bool = True) -> dict:
    """Preserve runtime item variants newer than the SDK's generated union."""
    result = client._client._request_raw(
        "thread/read", {"threadId": thread_id, "includeTurns": include_turns}
    )
    if not isinstance(result, dict) or not isinstance(result.get("thread"), dict):
        raise AxiError(
            "protocol_mismatch",
            "Codex returned an invalid thread response.",
            "Run `codex-axi doctor` and update the Codex SDK/runtime together.",
        )
    return result["thread"]
