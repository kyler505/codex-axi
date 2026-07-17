"""Stable AXI errors; raw runtime failures never become primary CLI output."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AxiError(Exception):
    code: str
    message: str
    suggestion: str
    exit_code: int = 1

    def document(self) -> dict[str, str]:
        return {"error": self.message, "code": self.code, "help": self.suggestion}


def translate_runtime_error(error: Exception) -> AxiError:
    text = str(error).lower()
    try:
        from openai_codex import InvalidParamsError, InvalidRequestError, TransportClosedError

        invalid_request_errors = (InvalidParamsError, InvalidRequestError)
        transport_errors = (TransportClosedError,)
    except ImportError:
        invalid_request_errors = ()
        transport_errors = ()

    missing_thread_markers = (
        "thread not found",
        "thread does not exist",
        "unknown thread",
        "thread not loaded",
        "no rollout found for thread id",
    )
    if any(marker in text for marker in missing_thread_markers):
        return AxiError(
            "thread_not_found",
            "The requested Codex thread was not found.",
            "Check the thread ID with `codex-axi task list --all-workspaces`.",
        )
    if isinstance(error, invalid_request_errors):
        return AxiError(
            "invalid_request",
            "Codex rejected the requested parameters.",
            "Check the command arguments and retry.",
            2,
        )
    if isinstance(error, transport_errors):
        return AxiError(
            "runtime_unavailable",
            "The Codex runtime connection closed unexpectedly.",
            "Run `codex-axi doctor` to inspect runtime compatibility.",
        )
    if "no module named" in text and "openai_codex" in text:
        return AxiError(
            "sdk_missing",
            "Codex SDK is not installed.",
            "Install codex-axi with its dependencies, then run `codex-axi doctor`.",
        )
    if "no such file" in text or "connection refused" in text or "transport" in text:
        return AxiError(
            "daemon_unavailable",
            "Managed Codex daemon is unavailable.",
            "Run `codex app-server daemon start`, then run `codex-axi doctor`.",
        )
    if "approval" in text or "denied" in text:
        return AxiError(
            "approval_required",
            "Codex could not continue without approval.",
            "Resume interactively or retry with an approval mode permitted by your policy.",
        )
    return AxiError(
        "runtime_unavailable",
        "Codex runtime connection failed.",
        "Run `codex-axi doctor` to inspect runtime compatibility.",
    )
