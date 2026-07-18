"""Runtime discovery and official SDK connection selection."""

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
SUPPORTED_SDK = ">=0.144,<0.145"


@dataclass(frozen=True)
class Capability:
    id: str
    status: str
    evidence: str
    detail: str | None = None

    def document(self) -> dict[str, object]:
        return {key: value for key, value in asdict(self).items() if value is not None}


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
    authenticated: bool | None = None
    shared_transport_available: bool = False
    shared_transport_detail: str | None = None

    def document(
        self, *, full: bool = True, rate_limits_available: bool | None = None
    ) -> dict[str, object]:
        document = asdict(self)
        document["execution_path"] = self.execution_path
        capabilities = self.capability_report(rate_limits_available=rate_limits_available)
        if full:
            document["capabilities"] = [item.document() for item in capabilities]
        else:
            statuses = (
                "supported",
                "detected",
                "degraded",
                "unsupported",
                "unknown",
                "unavailable",
            )
            document["capability_summary"] = {
                status: sum(item.status == status for item in capabilities)
                for status in statuses
                if any(item.status == status for item in capabilities)
            }
        document["unsupported_operations"] = [
            item.id for item in capabilities if item.status == "unsupported"
        ]
        document["degraded_operations"] = [
            item.id
            for item in capabilities
            if item.status in {"degraded", "unknown", "unavailable"}
        ]
        return document

    @property
    def execution_path(self) -> str:
        sdk_supported = _sdk_in_supported_range(self.sdk_version)
        if sdk_supported and self.shared_transport_available and self.daemon_state == "healthy":
            return "managed-proxy"
        if self.codex_path and sdk_supported:
            return "direct-stdio"
        return "unavailable"

    def capability_report(
        self, *, rate_limits_available: bool | None = None
    ) -> tuple[Capability, ...]:
        direct = bool(self.codex_path and _sdk_in_supported_range(self.sdk_version))
        try:
            from .integrations import integration_capability_statuses

            integrations = integration_capability_statuses()
        except Exception:
            integrations = {name: "unknown" for name in ("claude", "codex", "opencode")}
        rate_status = (
            "unknown"
            if rate_limits_available is None
            else ("supported" if rate_limits_available else "unavailable")
        )
        return (
            Capability(
                "runtime.version_policy",
                "supported" if _cli_in_supported_range(self.cli_version) else "degraded",
                "version_policy",
                f"tested range: {self.supported_codex}",
            ),
            Capability(
                "runtime.sdk_policy",
                "supported" if _sdk_in_supported_range(self.sdk_version) else "degraded",
                "version_policy",
                f"tested range: {SUPPORTED_SDK}",
            ),
            Capability("runtime.authenticated", _bool_status(self.authenticated), "probe"),
            Capability("execution.direct_stdio", _status(direct), "sdk_surface"),
            Capability(
                "transport.daemon", _daemon_capability(self.daemon_state), "probe", self.detail
            ),
            Capability(
                "transport.shared_attachment",
                _status(self.shared_transport_available),
                "sdk_surface",
                self.shared_transport_detail,
            ),
            Capability("observation.thread_read", _status(direct), "sdk_surface"),
            Capability("observation.rate_limits", rate_status, "probe"),
            Capability("observation.turn_events", _status(direct), "sdk_surface"),
            Capability("control.active_turn_owner", _status(direct), "sdk_surface"),
            Capability("output.toon", "supported", "fixture"),
            Capability("output.json", "supported", "fixture"),
            Capability("output.ndjson_events", "supported", "fixture"),
            Capability("integration.claude", integrations["claude"], "probe"),
            Capability("integration.codex", integrations["codex"], "probe"),
            Capability("integration.opencode", integrations["opencode"], "probe"),
        )


Run = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _status(value: bool) -> str:
    return "supported" if value else "unsupported"


def _bool_status(value: bool | None) -> str:
    return "unknown" if value is None else ("supported" if value else "unavailable")


def _daemon_capability(state: str) -> str:
    if state == "healthy":
        return "supported"
    return "unsupported" if state == "unavailable" else "degraded"


def _cli_in_supported_range(value: str | None) -> bool:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", value or "")
    return bool(match and (int(match.group(1)), int(match.group(2))) == (0, 144))


def _sdk_in_supported_range(value: str | None) -> bool:
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", value or "")
    return bool(match and (int(match.group(1)), int(match.group(2))) == (0, 144))


def _run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=False, timeout=10)


def _login_status(codex_path: str, run: Run) -> bool | None:
    """Return Codex's own non-interactive auth result without exposing credentials."""
    try:
        result = run((codex_path, "login", "status"))
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.returncode == 0


def probe_runtime(
    run: Run = _run,
    which: Callable[[str], str | None] = shutil.which,
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
    authenticated = _login_status(codex_path, run)
    version = run((codex_path, "--version"))
    version_text = version.stdout.strip() if version.returncode == 0 else None
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
            authenticated=authenticated,
        )
    shared_transport_detail = (
        "installed Codex SDK supports direct stdio only; managed Unix WebSocket attachment "
        "is unavailable"
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
                    authenticated=authenticated,
                    shared_transport_detail=shared_transport_detail,
                )
        except json.JSONDecodeError:
            pass
        return RuntimeCapabilities(
            codex_path,
            version_text,
            True,
            True,
            "healthy",
            "managed daemon protocol handshake completed",
            sdk_version,
            authenticated=authenticated,
            shared_transport_detail=shared_transport_detail,
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
    return RuntimeCapabilities(
        codex_path,
        version_text,
        True,
        True,
        state,
        detail,
        sdk_version,
        authenticated=authenticated,
        shared_transport_detail=shared_transport_detail,
    )


def read_rate_limits(capabilities: RuntimeCapabilities) -> dict[str, object]:
    """Read current account quota via the official SDK connection.

    The beta SDK has no public method for this endpoint. This narrow
    compatibility call reuses its managed connection rather than creating a
    second app-server client or reading Codex's private state files.
    """
    if not capabilities.codex_path:
        return _rate_limits_unavailable("Codex CLI is unavailable.")
    if capabilities.authenticated is False:
        return _rate_limits_unavailable("Codex is not authenticated.")
    try:
        client = open_connection(capabilities)
        try:
            raw = client._client._request_raw("account/rateLimits/read", {})
        finally:
            client.close()
    except Exception:
        return _rate_limits_unavailable(
            "This Codex SDK/runtime does not expose account rate-limit data."
        )
    if not isinstance(raw, dict) or not isinstance(raw.get("rateLimits"), dict):
        return _rate_limits_unavailable(
            "This Codex SDK/runtime returned an invalid rate-limit response."
        )
    snapshot = raw["rateLimits"]
    return {
        "available": True,
        "primary": _rate_limit_window(snapshot.get("primary")),
        "secondary": _rate_limit_window(snapshot.get("secondary")),
        "reached": snapshot.get("rateLimitReachedType"),
    }


def _rate_limits_unavailable(detail: str) -> dict[str, object]:
    return {
        "available": False,
        "detail": detail,
        "help": "Update Codex and the openai-codex SDK together, then run `codex-axi doctor`.",
    }


def _rate_limit_window(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    return {
        "used_percent": value.get("usedPercent"),
        "resets_at": value.get("resetsAt"),
        "window_duration_mins": value.get("windowDurationMins"),
    }


def open_connection(capabilities: RuntimeCapabilities):
    """Create an SDK client using only a transport the installed SDK supports."""
    if not capabilities.codex_path:
        raise AxiError(
            "codex_missing",
            "Codex CLI is unavailable.",
            "Install Codex, then run `codex-axi doctor`.",
        )
    try:
        from openai_codex import Codex, CodexConfig

        if capabilities.shared_transport_available and capabilities.daemon_state == "healthy":
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
