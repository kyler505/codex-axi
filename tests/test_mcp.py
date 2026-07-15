import pytest


def test_mcp_adapter_builds_from_shared_application_layer():
    pytest.importorskip("mcp")
    from codex_axi.mcp import build_server

    server = build_server()
    assert server.name == "codex-axi"
