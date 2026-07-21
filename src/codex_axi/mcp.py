"""Thin MCP adapter over the same :class:`CodexAxi` facade as the CLI."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .app import CodexAxi


def build_server(app_factory: Callable[[], CodexAxi] = CodexAxi):
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

    def execution_options(
        cwd: str | None,
        model: str | None,
        effort: str | None,
        sandbox: str,
        approval: str,
        full: bool,
        timeout: float,
        events: bool,
    ) -> dict[str, Any]:
        return {
            "cwd": cwd,
            "model": model,
            "effort": effort,
            "sandbox": sandbox,
            "approval": approval,
            "full": full,
            "timeout": timeout,
            "events": events,
        }

    @server.tool()
    def codex_task_start(
        message: str,
        cwd: str | None = None,
        model: str | None = None,
        effort: str | None = None,
        sandbox: str = "workspace-write",
        approval: str = "auto-review",
        full: bool = False,
        timeout: float = 0,
        events: bool = False,
    ) -> dict:
        return app_factory().start_task(
            message,
            **execution_options(cwd, model, effort, sandbox, approval, full, timeout, events),
        )

    @server.tool()
    def codex_task_list(
        all_workspaces: bool = False, archived: bool = False, limit: int = 100
    ) -> dict:
        return app_factory().list_tasks(
            all_workspaces=all_workspaces, archived=archived, limit=limit
        )

    @server.tool()
    def codex_task_status(thread: str, full: bool = False) -> dict:
        return app_factory().view_task(thread, full=full)

    @server.tool()
    def codex_task_resume(
        thread: str,
        message: str,
        cwd: str | None = None,
        model: str | None = None,
        effort: str | None = None,
        sandbox: str = "workspace-write",
        approval: str = "auto-review",
        full: bool = False,
        timeout: float = 0,
        events: bool = False,
    ) -> dict:
        return app_factory().resume_task(
            thread,
            message,
            **execution_options(cwd, model, effort, sandbox, approval, full, timeout, events),
        )

    @server.tool()
    def codex_task_follow(thread: str, full: bool = False, timeout: float = 0) -> dict:
        return app_factory().follow_task(thread, full=full, timeout=timeout)

    @server.tool()
    def codex_task_steer(thread: str, message: str, timeout: float = 5) -> dict:
        return app_factory().steer(thread, message, timeout=timeout)

    @server.tool()
    def codex_task_interrupt(thread: str) -> dict:
        return app_factory().interrupt(thread)

    @server.tool()
    def codex_task_archive(thread: str) -> dict:
        return app_factory().archive_task(thread)

    @server.tool()
    def codex_task_events(thread: str, since: int = 0, limit: int = 100) -> dict:
        return app_factory().events(thread, since=since, limit=limit)

    @server.tool()
    def codex_worker_start(
        message: str,
        role: str | None = None,
        label: str | None = None,
        background: bool = False,
        cwd: str | None = None,
        model: str | None = None,
        effort: str | None = None,
        sandbox: str = "workspace-write",
        approval: str = "auto-review",
        full: bool = False,
        timeout: float = 0,
        events: bool = False,
    ) -> dict:
        app = app_factory()
        method = app.start_worker_background if background else app.start_worker
        return method(
            message,
            role=role,
            label=label,
            **execution_options(cwd, model, effort, sandbox, approval, full, timeout, events),
        )

    @server.tool()
    def codex_worker_list(all_workspaces: bool = False) -> dict:
        return app_factory().list_workers(all_workspaces=all_workspaces)

    @server.tool()
    def codex_worker_status(thread: str, full: bool = False) -> dict:
        return app_factory().view_worker(thread, full=full)

    @server.tool()
    def codex_worker_send(thread: str, message: str, events: bool = False) -> dict:
        return app_factory().send_worker(thread, message, events=events)

    @server.tool()
    def codex_worker_follow(thread: str, full: bool = False, timeout: float = 0) -> dict:
        return app_factory().follow_worker(thread, full=full, timeout=timeout)

    @server.tool()
    def codex_worker_interrupt(thread: str) -> dict:
        result = app_factory().interrupt(thread)
        return {"worker": result["task"]}

    @server.tool()
    def codex_worker_close(thread: str) -> dict:
        return app_factory().close_worker(thread)

    @server.tool()
    def codex_worker_events(thread: str, since: int = 0, limit: int = 100) -> dict:
        return app_factory().events(thread, kind="worker", since=since, limit=limit)

    @server.tool()
    def codex_cleanup(retention_days: float = 30, dry_run: bool = True) -> dict:
        return app_factory().cleanup(retention_days=retention_days, dry_run=dry_run)

    @server.tool()
    def codex_agent_list(root_thread: str) -> dict:
        return app_factory().list_agents(root_thread)

    @server.tool()
    def codex_agent_status(thread: str, full: bool = False) -> dict:
        return app_factory().view_agent(thread, full=full)

    @server.tool()
    def codex_delegate(
        message: str,
        cwd: str | None = None,
        model: str | None = None,
        effort: str | None = None,
        sandbox: str = "workspace-write",
        approval: str = "auto-review",
        full: bool = False,
        timeout: float = 0,
        events: bool = False,
    ) -> dict:
        return app_factory().delegate(
            message,
            **execution_options(cwd, model, effort, sandbox, approval, full, timeout, events),
        )

    @server.tool()
    def codex_streaming_support() -> dict:
        return {
            "streaming": "unsupported",
            "detail": "MCP tools return bounded snapshots or wait for final state.",
            "help": (
                "Use codex_task_events or codex_worker_events with a sequence cursor; "
                "use the CLI with --follow --json for an NDJSON stream."
            ),
        }

    return server


def serve() -> None:
    build_server().run(transport="stdio")
