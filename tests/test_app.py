import os
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_axi.app import CodexAxi
from codex_axi.errors import AxiError
from codex_axi.runtime import RuntimeCapabilities
from codex_axi.state import StateStore


def app(tmp_path):
    return CodexAxi(
        cwd=Path("/repo"),
        store=StateStore(tmp_path / "state.json"),
        capabilities=RuntimeCapabilities("/bin/codex", "codex-cli 0.144.3", True, True, "healthy"),
    )


def test_worker_list_is_cwd_scoped(tmp_path):
    service = app(tmp_path)
    service.store.update_worker("one", cwd="/repo", kind="worker", status="running")
    service.store.update_worker("two", cwd="/elsewhere", kind="worker", status="done")
    assert service.list_workers()["count"] == 1
    assert service.list_workers(all_workspaces=True)["count"] == 2


def test_task_list_passes_cwd_filter_by_default(tmp_path):
    service = app(tmp_path)
    captured = {}

    class Client:
        def thread_list(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(data=[], next_cursor=None)

        def close(self):
            pass

    @contextmanager
    def fake_client():
        yield Client()

    service.client = fake_client
    service.list_tasks()
    assert captured["cwd"].root == "/repo"
    captured.clear()
    service.list_tasks(all_workspaces=True)
    assert "cwd" not in captured


@pytest.mark.parametrize("outcome", ["completed", "interrupted", "failed", "running"])
def test_task_list_prefers_tracked_outcome_over_sdk_load_state(tmp_path, outcome):
    service = app(tmp_path)
    service.store.update_task("thread-1", kind="task", status=outcome)

    class Client:
        def thread_list(self, **kwargs):
            return SimpleNamespace(
                data=[SimpleNamespace(id="thread-1", name="done", status="notLoaded")],
                next_cursor=None,
            )

        def close(self):
            pass

    @contextmanager
    def fake_client():
        yield Client()

    service.client = fake_client
    assert service.list_tasks()["tasks"][0]["status"] == outcome


def test_task_view_prefers_tracked_outcome_over_sdk_load_state(tmp_path, monkeypatch):
    service = app(tmp_path)
    service.store.update_task("thread-1", kind="task", status="interrupted")

    @contextmanager
    def fake_client():
        yield object()

    service.client = fake_client
    monkeypatch.setattr(
        "codex_axi.app.read_thread_compat",
        lambda *_: {
            "id": "thread-1",
            "status": "notLoaded",
            "turns": [],
        },
    )
    assert service.view_task("thread-1")["task"]["status"] == "interrupted"


def test_task_view_uses_sdk_status_for_untracked_thread(tmp_path, monkeypatch):
    service = app(tmp_path)

    @contextmanager
    def fake_client():
        yield object()

    service.client = fake_client
    monkeypatch.setattr(
        "codex_axi.app.read_thread_compat",
        lambda *_: {"id": "external", "status": "notLoaded", "turns": []},
    )
    assert service.view_task("external")["task"]["status"] == "notLoaded"


def test_task_view_reconciles_stale_running_status_from_turn_history(tmp_path, monkeypatch):
    service = app(tmp_path)
    service.store.update_task("thread-1", kind="task", status="running", owner_pid=1)
    service.store.set_active_turn("thread-1", "turn-1")

    @contextmanager
    def fake_client():
        yield object()

    service.client = fake_client
    monkeypatch.setattr(
        "codex_axi.app.read_thread_compat",
        lambda *_: {
            "id": "thread-1",
            "status": "notLoaded",
            "turns": [{"id": "turn-1", "status": "failed"}],
        },
    )
    assert service.view_task("thread-1")["task"]["status"] == "failed"
    assert service.store.task("thread-1")["status"] == "failed"
    assert service.store.active_turn("thread-1") is None


def test_task_view_prefers_newer_turn_outcome_over_old_metadata(tmp_path, monkeypatch):
    service = app(tmp_path)
    service.store.update_task("thread-1", kind="task", status="completed")

    @contextmanager
    def fake_client():
        yield object()

    service.client = fake_client
    monkeypatch.setattr(
        "codex_axi.app.read_thread_compat",
        lambda *_: {
            "id": "thread-1",
            "status": "notLoaded",
            "turns": [{"id": "turn-2", "status": "interrupted"}],
        },
    )
    assert service.view_task("thread-1")["task"]["status"] == "interrupted"


def test_task_list_reconciles_active_tasks_on_single_connection(tmp_path, monkeypatch):
    service = app(tmp_path)
    for index in (1, 2):
        thread_id = f"thread-{index}"
        service.store.update_task(thread_id, kind="task", status="running", owner_pid=1)
        service.store.set_active_turn(thread_id, f"turn-{index}")

    connections = 0

    class Client:
        def thread_list(self, **kwargs):
            return SimpleNamespace(
                data=[
                    SimpleNamespace(id=f"thread-{index}", status="notLoaded") for index in (1, 2)
                ],
                next_cursor=None,
            )

        def close(self):
            pass

    @contextmanager
    def fake_client():
        nonlocal connections
        connections += 1
        yield Client()

    service.client = fake_client
    monkeypatch.setattr(
        "codex_axi.app.read_thread_compat",
        lambda _, thread_id: {
            "id": thread_id,
            "turns": [
                {
                    "id": f"turn-{thread_id.rsplit('-', 1)[-1]}",
                    "status": "completed",
                }
            ],
        },
    )

    result = service.list_tasks()
    assert connections == 1
    assert [task["status"] for task in result["tasks"]] == ["completed", "completed"]
    assert service.store.active_turn("thread-1") is None
    assert service.store.active_turn("thread-2") is None


def test_task_list_keeps_metadata_when_shared_reconciliation_read_fails(tmp_path, monkeypatch):
    service = app(tmp_path)
    service.store.update_task("thread-1", kind="task", status="running", owner_pid=os.getpid())
    service.store.set_active_turn("thread-1", "turn-1")
    connections = 0

    class Client:
        def thread_list(self, **kwargs):
            return SimpleNamespace(
                data=[SimpleNamespace(id="thread-1", status="notLoaded")],
                next_cursor=None,
            )

        def close(self):
            pass

    @contextmanager
    def fake_client():
        nonlocal connections
        connections += 1
        yield Client()

    service.client = fake_client

    def fail_read(*_):
        raise RuntimeError("SDK read failed")

    monkeypatch.setattr("codex_axi.app.read_thread_compat", fail_read)

    result = service.list_tasks()
    assert connections == 1
    assert result["tasks"][0]["status"] == "running"
    assert service.store.active_turn("thread-1") == "turn-1"


def test_stale_turn_is_rejected_before_dependency_call(tmp_path):
    with pytest.raises(AxiError) as caught:
        app(tmp_path).interrupt("missing")
    assert caught.value.code == "stale_active_turn"


def test_native_agents_use_real_parent_metadata(tmp_path, monkeypatch):
    service = app(tmp_path)

    @contextmanager
    def client():
        yield object()

    service.client = client
    monkeypatch.setattr(
        "codex_axi.app.read_thread_compat",
        lambda _, thread: (
            {"turns": [{"items": [{"type": "subAgentActivity", "agentThreadId": "child"}]}]}
            if thread == "root"
            else {
                "id": "child",
                "agentNickname": "Ada",
                "agentRole": "reviewer",
                "status": {"type": "idle"},
                "parentThreadId": "root",
            }
        ),
    )
    result = service.list_agents("root")
    assert result["count"] == 1
    assert result["agents"][0]["parent_thread_id"] == "root"


def test_native_agent_with_mismatched_parent_is_excluded(tmp_path, monkeypatch):
    service = app(tmp_path)

    @contextmanager
    def client():
        yield object()

    service.client = client
    monkeypatch.setattr(
        "codex_axi.app.read_thread_compat",
        lambda _, thread: (
            {"turns": [{"items": [{"type": "subAgentActivity", "agentThreadId": "child"}]}]}
            if thread == "root"
            else {"id": "child", "parentThreadId": "another-root"}
        ),
    )
    assert service.list_agents("root") == {"count": 0, "agents": []}


def test_active_turn_control_is_applied_by_owner(tmp_path):
    service = app(tmp_path)
    service._collect_turn = lambda _, turn: turn.run()

    class Turn:
        id = "turn-1"

        def __init__(self):
            self.steered = threading.Event()

        def steer(self, message):
            assert message == "new direction"
            self.steered.set()

        def run(self):
            assert self.steered.wait(2)
            return SimpleNamespace(id=self.id)

    turn = Turn()
    service.store.set_active_turn("thread-1", turn.id)
    caller = threading.Thread(target=lambda: service.steer("thread-1", "new direction"))
    caller.start()
    service._run_controlled("thread-1", turn)
    caller.join(timeout=2)
    assert not caller.is_alive()


def test_foreground_timeout_interrupts_and_marks_task_interrupted(tmp_path):
    service = app(tmp_path)
    interrupted = threading.Event()

    class Turn:
        id = "turn-1"

        def interrupt(self):
            interrupted.set()

    class Thread:
        id = "thread-1"

        def turn(self, message, **kwargs):
            return Turn()

    class Client:
        def thread_start(self, **kwargs):
            return Thread()

        def close(self):
            pass

    @contextmanager
    def client():
        yield Client()

    service.client = client
    service._collect_turn = lambda _, __: interrupted.wait(1)
    with pytest.raises(AxiError) as caught:
        service.start_task("wait", timeout=0.01)
    assert caught.value.code == "turn_timeout"
    assert interrupted.is_set()
    assert service.store.task("thread-1")["status"] == "interrupted"
    assert service.store.active_turn("thread-1") is None


def test_steer_uses_requested_control_timeout(tmp_path, monkeypatch):
    service = app(tmp_path)
    service.store.update_task("thread-1", kind="task", status="running")
    service.store.set_active_turn("thread-1", "turn-1")
    monkeypatch.setattr(service, "_reconcile_active", lambda _, metadata: metadata)
    captured = {}
    monkeypatch.setattr(
        service,
        "_send_control",
        lambda thread, action, message, *, timeout: captured.update(timeout=timeout),
    )
    service.steer("thread-1", "change direction", timeout=0.25)
    assert captured["timeout"] == 0.25


def test_close_worker_is_idempotent_without_second_dependency_call(tmp_path, monkeypatch):
    service = app(tmp_path)
    service.store.update_worker("thread-1", kind="worker", status="closed")
    monkeypatch.setattr(
        service,
        "client",
        lambda: (_ for _ in ()).throw(AssertionError("dependency called")),
    )
    assert service.close_worker("thread-1")["worker"]["status"] == "already_closed"


def test_resume_applies_requested_runtime_policy(tmp_path):
    service = app(tmp_path)
    service._collect_turn = lambda _, turn: turn.run()
    captured = {}

    class Turn:
        id = "turn-1"

        def run(self):
            return SimpleNamespace(
                id=self.id,
                status="completed",
                final_response="done",
                duration_ms=1,
            )

    class Thread:
        id = "thread-1"

        def turn(self, message, **kwargs):
            captured["turn"] = kwargs
            return Turn()

    class Client:
        def thread_resume(self, thread_id, **kwargs):
            captured["resume"] = kwargs
            return Thread()

        def close(self):
            pass

    @contextmanager
    def fake_client():
        yield Client()

    service.client = fake_client
    service.resume_task(
        "thread-1",
        "continue",
        cwd=Path("/repo"),
        model="gpt-test",
        sandbox="read-only",
        approval="deny-all",
    )
    assert captured["resume"]["model"] == "gpt-test"
    assert captured["resume"]["sandbox"].value == "read-only"
    assert captured["resume"]["approval_mode"].value == "deny_all"
    assert captured["turn"]["sandbox"].value == "read-only"


def test_reconciliation_uses_runtime_turn_status(tmp_path, monkeypatch):
    service = app(tmp_path)
    service.store.update_worker(
        "thread-1", kind="worker", status="running", owner_pid=1, cwd="/repo"
    )
    service.store.set_active_turn("thread-1", "turn-1")

    @contextmanager
    def client():
        yield object()

    service.client = client
    monkeypatch.setattr(
        "codex_axi.app.read_thread_compat",
        lambda *_: {"turns": [{"id": "turn-1", "status": "completed"}]},
    )
    result = service.list_workers()
    assert result["workers"][0]["status"] == "completed"
    assert service.store.active_turn("thread-1") is None


def test_reconciliation_keeps_live_owner_authoritative(tmp_path, monkeypatch):
    service = app(tmp_path)
    service.store.update_worker(
        "thread-1", kind="worker", status="running", owner_pid=os.getpid(), cwd="/repo"
    )
    service.store.set_active_turn("thread-1", "turn-1")
    monkeypatch.setattr(
        "codex_axi.app.read_thread_compat",
        lambda *_: pytest.fail("live owner should not be reconciled through another runtime"),
    )

    result = service._reconcile_active("thread-1", service.store.worker("thread-1"))

    assert result["status"] == "running"
    assert service.store.active_turn("thread-1") == "turn-1"


def test_reconciliation_uses_dead_lease_when_runtime_read_fails(tmp_path, monkeypatch):
    service = app(tmp_path)
    service.store.update_worker(
        "thread-1",
        kind="worker",
        status="running",
        owner_pid=os.getpid(),
        pid=os.getpid(),
        background=True,
        runner_lease=str(tmp_path / "inactive.lease"),
        cwd="/repo",
    )
    service.store.set_active_turn("thread-1", "turn-1")

    @contextmanager
    def failed_client():
        raise RuntimeError("read failed")
        yield

    service.client = failed_client
    result = service._reconcile_active("thread-1", service.store.worker("thread-1"))

    assert result["status"] == "interrupted"
    assert service.store.active_turn("thread-1") is None


def test_close_worker_interrupts_then_confirms_background_process_exit(tmp_path, monkeypatch):
    service = app(tmp_path)
    service.store.update_worker(
        "thread-1",
        kind="worker",
        status="running",
        owner_pid=4321,
        pid=4321,
        background=True,
        runner_lease="/tmp/runner.lease",
        cwd="/repo",
    )
    service.store.set_active_turn("thread-1", "turn-1")
    controls = []
    monkeypatch.setattr(
        service,
        "_send_control",
        lambda thread, action: controls.append((thread, action)),
    )
    monkeypatch.setattr("codex_axi.app._wait_pid_exit", lambda *_args, **_kwargs: True)
    monkeypatch.setattr("codex_axi.app._runner_lease_active", lambda _path: True)

    class Client:
        def thread_archive(self, thread_id):
            assert thread_id == "thread-1"

        def close(self):
            pass

    @contextmanager
    def fake_client():
        yield Client()

    service.client = fake_client
    result = service.close_worker("thread-1")

    assert controls == [("thread-1", "interrupt")]
    assert result["worker"]["status"] == "closed"
    assert service.store.worker("thread-1")["status"] == "closed"


def test_close_completed_worker_never_acts_on_historical_pid(tmp_path, monkeypatch):
    service = app(tmp_path)
    service.store.update_worker(
        "thread-1",
        kind="worker",
        status="completed",
        owner_pid=None,
        pid=4321,
        background=True,
        cwd="/repo",
    )
    monkeypatch.setattr(
        "codex_axi.app._wait_pid_exit",
        lambda *_args, **_kwargs: pytest.fail("historical PID must not be inspected"),
    )
    monkeypatch.setattr(
        "codex_axi.app._runner_lease_active",
        lambda _path: pytest.fail("completed worker lease must not be inspected"),
    )

    class Client:
        def thread_archive(self, thread_id):
            assert thread_id == "thread-1"

        def close(self):
            pass

    @contextmanager
    def fake_client():
        yield Client()

    service.client = fake_client
    assert service.close_worker("thread-1")["worker"]["status"] == "closed"


def test_close_fails_truthfully_when_runner_does_not_exit(tmp_path, monkeypatch):
    service = app(tmp_path)
    service.store.update_worker(
        "thread-1",
        kind="worker",
        status="running",
        owner_pid=4321,
        pid=4321,
        background=True,
        runner_lease="/tmp/runner.lease",
        cwd="/repo",
    )
    service.store.set_active_turn("thread-1", "turn-1")
    monkeypatch.setattr(service, "_send_control", lambda *_args: None)
    monkeypatch.setattr("codex_axi.app._runner_lease_active", lambda _path: True)
    monkeypatch.setattr("codex_axi.app._wait_pid_exit", lambda *_args, **_kwargs: False)

    with pytest.raises(AxiError) as caught:
        service.close_worker("thread-1")

    assert caught.value.code == "worker_close_failed"
    assert service.store.worker("thread-1")["status"] == "close_failed"


def test_close_archive_failure_is_recoverable(tmp_path):
    service = app(tmp_path)
    service.store.update_worker("thread-1", kind="worker", status="completed", cwd="/repo")

    class Client:
        def thread_archive(self, thread_id):
            raise RuntimeError("archive failed")

        def close(self):
            pass

    @contextmanager
    def fake_client():
        yield Client()

    service.client = fake_client
    with pytest.raises(RuntimeError, match="archive failed"):
        service.close_worker("thread-1")
    assert service.store.worker("thread-1")["status"] == "close_failed"


def test_turn_started_event_confirms_active_identifier(tmp_path):
    service = app(tmp_path)
    agent_item = SimpleNamespace(type="agentMessage", phase="final_answer", text="done")
    completed_turn = SimpleNamespace(
        id="turn-1",
        status="completed",
        error=None,
        started_at=1,
        completed_at=2,
        duration_ms=1,
    )

    class Turn:
        id = "turn-1"

        def stream(self):
            yield SimpleNamespace(
                method="turn/started",
                payload=SimpleNamespace(turn=SimpleNamespace(id="turn-1")),
            )
            yield SimpleNamespace(
                method="item/completed",
                payload=SimpleNamespace(turn_id="turn-1", item=agent_item),
            )
            yield SimpleNamespace(
                method="turn/completed", payload=SimpleNamespace(turn=completed_turn)
            )

    result = service._collect_turn("thread-1", Turn())
    assert service.store.active_turn("thread-1") == "turn-1"
    assert result.final_response == "done"


def test_turn_event_capture_is_passive(tmp_path):
    service = app(tmp_path)
    emitted = []
    agent_item = SimpleNamespace(type="agentMessage", phase="final_answer", text="done")
    completed_turn = SimpleNamespace(
        id="turn-1",
        status="completed",
        error=None,
        started_at=1,
        completed_at=2,
        duration_ms=1,
    )

    class Journal:
        def emit(self, event):
            emitted.append(event.method)

    class Turn:
        id = "turn-1"

        def stream(self):
            yield SimpleNamespace(
                method="item/completed",
                payload=SimpleNamespace(turn_id="turn-1", item=agent_item),
            )
            yield SimpleNamespace(
                method="turn/completed", payload=SimpleNamespace(turn=completed_turn)
            )

    result = service._collect_turn("thread-1", Turn(), journal=Journal())
    assert emitted == ["item/completed", "turn/completed"]
    assert result.final_response == "done"


def test_events_reports_definitive_not_captured_state(tmp_path):
    service = app(tmp_path)
    service.store.update_task("thread-1", kind="task", status="completed")

    result = service.events("thread-1")
    assert result["count"] == 0
    assert result["status"] == "not_captured"


def test_new_turn_without_capture_clears_stale_event_metadata(tmp_path):
    service = app(tmp_path)
    service.store.update_task("thread-1", event_log="/tmp/old.jsonl", event_turn_id="old-turn")

    assert service._prepare_events("thread-1", "new-turn", "task", {}) is None
    metadata = service.store.task("thread-1")
    assert metadata["event_log"] is None
    assert metadata["event_turn_id"] is None


def test_event_journal_creation_failure_is_passive(tmp_path, monkeypatch):
    service = app(tmp_path)
    service.store.update_task(
        "thread-1", event_log="/tmp/stale.jsonl", event_turn_id="old-turn"
    )
    def fail_creation(*_args):
        raise OSError("disk full")

    monkeypatch.setattr("codex_axi.app.EventJournal.create", fail_creation)

    journal = service._prepare_events(
        "thread-1", "new-turn", "task", {"events": True}
    )

    assert journal is None
    metadata = service.store.task("thread-1")
    assert metadata["event_log"] is None
    assert metadata["event_turn_id"] is None


def test_controlled_turn_marks_event_writer_finished(tmp_path):
    service = app(tmp_path)
    finished = threading.Event()

    class Journal:
        def finish(self):
            finished.set()

    class Turn:
        id = "turn-1"

    service._collect_turn = lambda *_args, **_kwargs: SimpleNamespace(id="turn-1")

    service._run_controlled("thread-1", Turn(), journal=Journal())

    assert finished.is_set()
