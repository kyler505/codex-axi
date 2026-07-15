from pathlib import Path

from codex_axi.app import CodexAxi
from codex_axi.runtime import RuntimeCapabilities
from codex_axi.state import StateStore


def test_send_steers_active_worker_instead_of_starting_parallel_turn(tmp_path, monkeypatch):
    store = StateStore(tmp_path / "state.json")
    store.update_worker("thread-1", kind="worker", status="running")
    store.set_active_turn("thread-1", "turn-1")
    service = CodexAxi(
        cwd=Path("/repo"),
        store=store,
        capabilities=RuntimeCapabilities("/bin/codex", "0.144.3", True, True, "healthy"),
    )
    monkeypatch.setattr(
        service,
        "steer",
        lambda thread, message: {"task": {"id": thread, "turn_id": "turn-1", "status": "steered"}},
    )
    result = service.send_worker("thread-1", "new direction")
    assert result["worker"]["status"] == "steered"
