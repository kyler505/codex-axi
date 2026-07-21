import pytest


def test_mcp_adapter_builds_from_shared_application_layer():
    pytest.importorskip("mcp")
    from codex_axi.mcp import build_server

    server = build_server()
    assert server.name == "codex-axi"
    names = {tool.name for tool in server._tool_manager.list_tools()}
    assert {
        "codex_task_start",
        "codex_task_resume",
        "codex_task_follow",
        "codex_task_events",
        "codex_task_archive",
        "codex_worker_start",
        "codex_worker_follow",
        "codex_worker_close",
        "codex_worker_events",
        "codex_cleanup",
        "codex_agent_list",
        "codex_agent_status",
        "codex_delegate",
        "codex_streaming_support",
    } <= names


def test_mcp_forwards_safety_and_lifecycle_defaults_to_facade():
    pytest.importorskip("mcp")
    from codex_axi.mcp import build_server

    calls = []

    class App:
        def start_task(self, message, **options):
            calls.append((message, options))
            return {"ok": True}

    server = build_server(lambda: App())
    tool = server._tool_manager.get_tool("codex_task_start")
    assert tool.fn("work") == {"ok": True}
    assert calls == [
        (
            "work",
            {
                "cwd": None,
                "model": None,
                "effort": None,
                "sandbox": "workspace-write",
                "approval": "auto-review",
                "full": False,
                "timeout": 0,
                "events": False,
            },
        )
    ]


def test_mcp_reports_streaming_boundary_actionably():
    pytest.importorskip("mcp")
    from codex_axi.mcp import build_server

    server = build_server()
    result = server._tool_manager.get_tool("codex_streaming_support").fn()
    assert result["streaming"] == "unsupported"
    assert "--follow --json" in result["help"]
