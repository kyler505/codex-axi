import os

from codex_axi.events import EventJournal
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
    assert controls[0] | {"created_at": None} == {
        "id": control_id,
        "action": "steer",
        "message": "new direction",
        "created_at": None,
    }
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


def test_state_supports_unicode_and_spaces_in_path(tmp_path):
    path = tmp_path / "state dir ü" / "state file.json"
    store = StateStore(path)
    store.update_task("thread-ü", status="completed")
    assert store.task("thread-ü")["status"] == "completed"
    assert not list(path.parent.glob("state.*.json"))


def test_cleanup_dry_run_then_idempotently_prunes_expired_workspace_state(tmp_path):
    path = tmp_path / "state.json"
    store = StateStore(path)
    workspace = tmp_path / "project"
    workspace.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    store.update_task("stale", cwd=str(workspace), status="completed")
    store.update_task("other", cwd=str(other), status="completed")
    journal = EventJournal.create(path, "stale", "turn")
    journal.finish()
    old = 1_000.0
    os.utime(journal.path, (old, old))
    store.update_task("stale", event_log=str(journal.path), event_turn_id="turn")
    data = store.read()
    data["controls"] = {
        "stale": [{"id": "old", "action": "interrupt", "created_at": old}],
        "other": [{"id": "keep", "action": "interrupt", "created_at": old}],
    }
    data["control_results"] = {
        "result": {"status": "applied", "created_at": old, "thread_id": "stale"}
    }
    store._write(data)

    preview = store.cleanup(retention_days=1, workspace=workspace, dry_run=True, now=200_000)
    assert preview["cleanup"]["status"] == "would_remove"
    assert journal.path.exists()
    result = store.cleanup(retention_days=1, workspace=workspace, now=200_000)
    assert result["cleanup"]["removed"]["event_journals"] == 1
    assert store.read()["controls"]["other"][0]["id"] == "keep"
    assert (
        store.cleanup(retention_days=1, workspace=workspace, now=200_000)["cleanup"]["status"]
        == "no_op"
    )
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600


def test_cleanup_preserves_active_journal_and_control(tmp_path):
    path = tmp_path / "state.json"
    store = StateStore(path)
    workspace = tmp_path / "project"
    workspace.mkdir()
    store.update_worker("active", cwd=str(workspace), status="running")
    journal = EventJournal.create(path, "active", "turn")
    store.update_worker("active", event_log=str(journal.path), event_turn_id="turn")
    store.set_active_turn("active", "turn")
    data = store.read()
    data["controls"] = {"active": [{"id": "old", "action": "interrupt", "created_at": 1_000.0}]}
    store._write(data)
    result = store.cleanup(retention_days=1, workspace=workspace, now=200_000)
    assert result["cleanup"]["status"] == "no_op"
    assert journal.path.exists()
    journal.finish()
