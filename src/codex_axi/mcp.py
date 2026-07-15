"""Thin MCP adapter over the same application layer as the CLI."""

from __future__ import annotations

from .app import CodexAxi


def build_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as error:
        from .errors import AxiError

        raise AxiError(
            "mcp_unavailable",
            "MCP support is not installed.",
            "Install `codex-axi[mcp]` and retry.",
        ) from error
    server = FastMCP("codex-axi")

    @server.tool()
    def codex_task_start(message: str, cwd: str | None = None) -> dict:
        return CodexAxi().start_task(message, **({"cwd": cwd} if cwd else {}))

    @server.tool()
    def codex_task_status(thread: str) -> dict:
        return CodexAxi().view_task(thread)

    @server.tool()
    def codex_task_steer(thread: str, message: str) -> dict:
        return CodexAxi().steer(thread, message)

    @server.tool()
    def codex_task_interrupt(thread: str) -> dict:
        return CodexAxi().interrupt(thread)

    @server.tool()
    def codex_worker_start(message: str, role: str | None = None) -> dict:
        return CodexAxi().start_worker(message, role=role)

    @server.tool()
    def codex_worker_list() -> dict:
        return CodexAxi().list_workers()

    return server


def serve() -> None:
    build_server().run(transport="stdio")
