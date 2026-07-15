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
