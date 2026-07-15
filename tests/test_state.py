from codex_axi.state import StateStore


def test_worker_state_round_trip_and_removal(tmp_path):
    store = StateStore(tmp_path / "state.json")
    store.update_worker("thread-1", kind="worker", status="running", active_turn_id="turn-1")
    assert store.worker("thread-1")["kind"] == "worker"
    assert store.remove_worker("thread-1") is True
    assert store.remove_worker("thread-1") is False


def test_active_turn_round_trip(tmp_path):
    store = StateStore(tmp_path / "state.json")
    store.set_active_turn("thread-1", "turn-1")
    assert store.active_turn("thread-1") == "turn-1"
    store.set_active_turn("thread-1", None)
    assert store.active_turn("thread-1") is None


def test_control_queue_is_acknowledged(tmp_path):
    store = StateStore(tmp_path / "state.json")
    control_id = store.enqueue_control("thread-1", "steer", "new direction")
    controls = store.take_controls("thread-1")
    assert controls == [{"id": control_id, "action": "steer", "message": "new direction"}]
    store.finish_control(control_id, status="applied")
    assert store.control_result(control_id)["status"] == "applied"


def test_worker_metadata_never_claims_native_subagent(tmp_path):
    store = StateStore(tmp_path / "state.json")
    store.update_worker("thread-1", kind="worker")
    assert store.worker("thread-1") == {"kind": "worker"}


def test_malformed_state_recovers_to_definitive_empty_state(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("not json")
    assert StateStore(path).workers() == {}
    assert list(tmp_path.glob("state.json.corrupt.*"))
