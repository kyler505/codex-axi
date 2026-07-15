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
