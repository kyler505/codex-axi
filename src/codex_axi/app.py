"""Application layer shared by the CLI and MCP adapter."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .errors import AxiError, translate_runtime_error
from .output import preview
from .runtime import RuntimeCapabilities, open_connection, probe_runtime, read_thread_compat
from .state import StateStore


def model_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=False)
    if isinstance(value, dict):
        return value
    return vars(value)


class CodexAxi:
    def __init__(
        self,
        *,
        cwd: Path | None = None,
        store: StateStore | None = None,
        capabilities: RuntimeCapabilities | None = None,
    ) -> None:
        self.cwd = (cwd or Path.cwd()).resolve()
        self.store = store or StateStore()
        self.capabilities = capabilities or probe_runtime()

    @contextmanager
    def client(self) -> Iterator[Any]:
        client = open_connection(self.capabilities)
        try:
            yield client
        except AxiError:
            raise
        except Exception as error:
            raise translate_runtime_error(error) from error
        finally:
            client.close()

    def list_tasks(
        self, *, all_workspaces: bool = False, archived: bool | None = False, limit: int = 100
    ) -> dict[str, Any]:
        with self.client() as client:
            kwargs: dict[str, Any] = {"archived": archived, "limit": limit}
            if not all_workspaces:
                from openai_codex.types import ThreadListCwdFilter

                kwargs["cwd"] = ThreadListCwdFilter(root=str(self.cwd))
            response = client.thread_list(**kwargs)
        rows = [self._thread_summary(thread) for thread in response.data]
        result = {
            "returned": len(rows),
            "total": None,
            "tasks": rows,
            "has_more": response.next_cursor is not None,
        }
        result["help"] = ["codex-axi task view <thread>", 'codex-axi task start --message "<task>"']
        return result

    def view_task(self, thread_id: str, *, full: bool = False) -> dict[str, Any]:
        with self.client() as client:
            data = read_thread_compat(client, thread_id)
        metadata = self.store.task(thread_id) or self.store.worker(thread_id) or {}
        body, total = preview(data.get("preview", ""), limit=800 if not full else 10**9)
        final_response = _last_response(data)
        final_shown, final_total = preview(final_response, limit=800 if not full else 10**9)
        result = {
            "task": {
                "id": data["id"],
                "name": data.get("name"),
                "status": metadata.get("status", _enum(data.get("status"))),
                "cwd": data.get("cwd"),
                "preview": body,
                "final_response": final_shown,
                "turns": len(data.get("turns", [])),
                "sandbox": metadata.get("sandbox", "unknown"),
                "approval": metadata.get("approval", "unknown"),
                "parent_thread_id": data.get("parentThreadId"),
            }
        }
        if total is not None:
            result["task"]["preview_chars"] = total
            result["help"] = [f"codex-axi task view {thread_id} --full"]
        if final_total is not None:
            result["task"]["final_response_chars"] = final_total
            result["help"] = [f"codex-axi task view {thread_id} --full"]
        return result

    def follow_task(
        self, thread_id: str, *, full: bool = False, timeout: float = 0
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout if timeout else None
        while True:
            result = self.view_task(thread_id, full=full)
            if result["task"]["status"] not in {"active", "running"}:
                return result
            if deadline and time.monotonic() >= deadline:
                raise AxiError(
                    "follow_timeout",
                    f"Task {thread_id} is still active.",
                    f"Run `codex-axi task follow {thread_id}` to continue waiting.",
                )
            time.sleep(0.2)

    def view_agent(self, thread_id: str, *, full: bool = False) -> dict[str, Any]:
        result = self.view_task(thread_id, full=full)
        if not result["task"].get("parent_thread_id"):
            raise AxiError(
                "not_native_agent",
                f"Thread {thread_id} is not a native Codex subagent.",
                "Run `codex-axi agent list <root-thread>`.",
            )
        return {"agent": result["task"], **({"help": result["help"]} if "help" in result else {})}

    def start_task(self, message: str, **options: Any) -> dict[str, Any]:
        with self.client() as client:
            thread = self._start_thread(client, **options)
            self.store.update_task(
                thread.id,
                kind="task",
                cwd=str(options.get("cwd") or self.cwd),
                sandbox=options.get("sandbox", "workspace-write"),
                approval=options.get("approval", "auto-review"),
                model=options.get("model"),
                owner_pid=os.getpid(),
                status="running",
            )
            turn = thread.turn(message, **self._turn_options(options))
            self.store.set_active_turn(thread.id, turn.id)
            try:
                result = self._run_controlled(thread.id, turn, timeout=options.get("timeout", 0))
            except BaseException as error:
                self.store.update_task(
                    thread.id,
                    owner_pid=None,
                    status=_interruption_status(error),
                )
                raise
            finally:
                self.store.set_active_turn(thread.id, None)
            self.store.update_task(thread.id, owner_pid=None, status=_enum(result.status))
        return self._result(thread.id, result, full=bool(options.get("full")))

    def resume_task(self, thread_id: str, message: str, **options: Any) -> dict[str, Any]:
        with self.client() as client:
            thread = client.thread_resume(thread_id, **self._lifecycle_options(options))
            metadata = {
                "cwd": str(options.get("cwd") or self.cwd),
                "sandbox": options.get("sandbox", "workspace-write"),
                "approval": options.get("approval", "auto-review"),
                "model": options.get("model"),
            }
            if self.store.worker(thread.id):
                self.store.update_worker(
                    thread.id, **metadata, owner_pid=os.getpid(), status="running"
                )
            else:
                self.store.update_task(
                    thread.id, **metadata, owner_pid=os.getpid(), status="running"
                )
            turn = thread.turn(message, **self._turn_options(options))
            self.store.set_active_turn(thread.id, turn.id)
            try:
                result = self._run_controlled(thread.id, turn, timeout=options.get("timeout", 0))
            except BaseException as error:
                values = {
                    "owner_pid": None,
                    "status": _interruption_status(error),
                }
                if self.store.worker(thread.id):
                    self.store.update_worker(thread.id, **values)
                else:
                    self.store.update_task(thread.id, **values)
                raise
            finally:
                self.store.set_active_turn(thread.id, None)
            if not self.store.worker(thread.id):
                self.store.update_task(thread.id, owner_pid=None, status=_enum(result.status))
        return self._result(thread.id, result, full=bool(options.get("full")))

    def archive_task(self, thread_id: str) -> dict[str, Any]:
        existing = self.store.task(thread_id)
        if existing and existing.get("status") == "archived":
            return {"task": {"id": thread_id, "status": "already_archived"}}
        with self.client() as client:
            try:
                client.thread_archive(thread_id)
                state = "archived"
            except Exception as error:
                if "archiv" in str(error).lower() and "already" in str(error).lower():
                    state = "already_archived"
                else:
                    raise
        if existing:
            self.store.update_task(thread_id, status="archived")
        return {"task": {"id": thread_id, "status": state}}

    def close_worker(self, thread_id: str) -> dict[str, Any]:
        worker = self.store.worker(thread_id)
        if not worker:
            raise AxiError(
                "worker_not_found",
                f"Worker {thread_id} is not managed by codex-axi.",
                "Run `codex-axi worker list`.",
            )
        if worker.get("status") == "closed":
            return {"worker": {"id": thread_id, "status": "already_closed"}}
        with self.client() as client:
            client.thread_archive(thread_id)
        self.store.set_active_turn(thread_id, None)
        self.store.update_worker(thread_id, status="closed", active_turn_id=None)
        return {"worker": {"id": thread_id, "status": "closed"}}

    def start_worker(
        self,
        message: str,
        *,
        role: str | None = None,
        label: str | None = None,
        _rendezvous: Path | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        with self.client() as client:
            thread = self._start_thread(
                client, developer_instructions=_worker_instructions(role), **options
            )
            turn = thread.turn(message, **self._turn_options(options))
            self.store.set_active_turn(thread.id, turn.id)
            self.store.update_worker(
                thread.id,
                kind="worker",
                cwd=str(options.get("cwd") or self.cwd),
                role=role,
                label=label,
                active_turn_id=turn.id,
                status="running",
                owner_pid=os.getpid(),
                sandbox=options.get("sandbox", "workspace-write"),
                approval=options.get("approval", "auto-review"),
                model=options.get("model"),
                effort=options.get("effort"),
            )
            if _rendezvous:
                _rendezvous.write_text(
                    json.dumps({"thread_id": thread.id, "turn_id": turn.id}) + "\n"
                )
            try:
                result = self._run_controlled(thread.id, turn, timeout=options.get("timeout", 0))
                self.store.set_active_turn(thread.id, None)
                self.store.update_worker(
                    thread.id,
                    active_turn_id=None,
                    status=_enum(result.status),
                    final_response=result.final_response,
                    owner_pid=None,
                )
            except BaseException as error:
                self.store.set_active_turn(thread.id, None)
                self.store.update_worker(
                    thread.id, owner_pid=None, status=_interruption_status(error)
                )
                raise
        return self._result(thread.id, result, kind="worker", full=bool(options.get("full")))

    def start_worker_background(
        self, message: str, *, role: str | None = None, label: str | None = None, **options: Any
    ) -> dict[str, Any]:
        run_dir = self.store.path.parent / "runs"
        run_dir.mkdir(parents=True, exist_ok=True)
        fd, request_name = tempfile.mkstemp(dir=run_dir, prefix="request.", suffix=".json")
        os.close(fd)
        request_path = Path(request_name)
        rendezvous = request_path.with_suffix(".ready.json")
        log_path = request_path.with_suffix(".log")
        payload = {
            "message": message,
            "role": role,
            "label": label,
            "options": {
                key: str(value) if isinstance(value, Path) else value
                for key, value in options.items()
            },
            "state": str(self.store.path),
            "cwd": str(self.cwd),
            "rendezvous": str(rendezvous),
        }
        request_path.write_text(json.dumps(payload) + "\n")
        with log_path.open("a") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "codex_axi.runner", str(request_path)],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if rendezvous.exists():
                ready = json.loads(rendezvous.read_text())
                request_path.unlink(missing_ok=True)
                rendezvous.unlink(missing_ok=True)
                self.store.update_worker(
                    ready["thread_id"], pid=process.pid, log=str(log_path), background=True
                )
                return {
                    "worker": {
                        "id": ready["thread_id"],
                        "turn_id": ready["turn_id"],
                        "status": "running",
                        "pid": process.pid,
                    }
                }
            if process.poll() is not None:
                raise AxiError(
                    "worker_start_failed",
                    "Background worker exited before creating a turn.",
                    f"Inspect `{log_path}` and run `codex-axi doctor`.",
                )
            time.sleep(0.05)
        process.terminate()
        raise AxiError(
            "worker_start_timeout",
            "Background worker did not publish thread identifiers in time.",
            f"Inspect `{log_path}` and run `codex-axi doctor`.",
        )

    def list_workers(self, *, all_workspaces: bool = False) -> dict[str, Any]:
        workers = self.store.workers()
        rows = []
        for thread_id, item in workers.items():
            if item.get("status") == "running":
                item = self._reconcile_active(thread_id, item)
            if all_workspaces or Path(item.get("cwd", "")).resolve() == self.cwd:
                rows.append(
                    {
                        "id": thread_id,
                        "label": item.get("label"),
                        "status": item.get("status"),
                        "role": item.get("role"),
                    }
                )
        return {
            "count": len(rows),
            "workers": rows,
            "help": ['codex-axi worker start --message "<task>"', "codex-axi worker view <thread>"],
        }

    def view_worker(self, thread_id: str, *, full: bool = False) -> dict[str, Any]:
        item = self.store.worker(thread_id)
        if not item:
            raise AxiError(
                "worker_not_found",
                f"Worker {thread_id} is not managed by codex-axi.",
                "Run `codex-axi worker list`.",
            )
        if item.get("status") == "running":
            item = self._reconcile_active(thread_id, item)
        response = item.get("final_response") or ""
        shown, total = preview(response, limit=800 if not full else 10**9)
        result: dict[str, Any] = {
            "worker": {
                "id": thread_id,
                **{k: v for k, v in item.items() if k != "final_response"},
                "result": shown,
            }
        }
        if total is not None:
            result["worker"]["result_chars"] = total
            result["help"] = [f"codex-axi worker view {thread_id} --full"]
        return result

    def follow_worker(
        self, thread_id: str, *, full: bool = False, timeout: float = 0
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout if timeout else None
        while True:
            item = self.store.worker(thread_id)
            if not item:
                return self.view_worker(thread_id, full=full)
            if item.get("status") != "running":
                return self.view_worker(thread_id, full=full)
            if deadline and time.monotonic() >= deadline:
                raise AxiError(
                    "follow_timeout",
                    f"Worker {thread_id} is still running.",
                    f"Run `codex-axi worker follow {thread_id}` to continue waiting.",
                )
            time.sleep(0.2)

    def send_worker(self, thread_id: str, message: str, **options: Any) -> dict[str, Any]:
        worker = self.store.worker(thread_id)
        if not worker:
            raise AxiError(
                "worker_not_found",
                f"Worker {thread_id} is not managed by codex-axi.",
                "Run `codex-axi worker list`.",
            )
        if self.store.active_turn(thread_id):
            result = self.steer(thread_id, message)
            return {"worker": result["task"]}
        preserved = {
            key: worker[key]
            for key in ("cwd", "model", "effort", "sandbox", "approval")
            if worker.get(key) is not None
        }
        preserved.update(options)
        result = self.resume_task(thread_id, message, **preserved)
        task = result["task"]
        self.store.update_worker(
            thread_id,
            status=task["status"],
            final_response=task["final_response"],
            owner_pid=None,
            active_turn_id=None,
        )
        return {"worker": task}

    def steer(self, thread_id: str, message: str, *, timeout: float = 5) -> dict[str, Any]:
        turn_id = self._active_turn(thread_id)
        self._send_control(thread_id, "steer", message, timeout=timeout)
        return {"task": {"id": thread_id, "turn_id": turn_id, "status": "steered"}}

    def interrupt(self, thread_id: str) -> dict[str, Any]:
        turn_id = self._active_turn(thread_id)
        self._send_control(thread_id, "interrupt")
        if self.store.worker(thread_id):
            self.store.update_worker(thread_id, active_turn_id=None, status="interrupted")
        return {"task": {"id": thread_id, "turn_id": turn_id, "status": "interrupted"}}

    def list_agents(self, root_thread: str) -> dict[str, Any]:
        with self.client() as client:
            root = read_thread_compat(client, root_thread)
            child_ids = []
            for turn in root.get("turns", []):
                for item in turn.get("items", []):
                    if item.get("type") == "subAgentActivity" and item.get("agentThreadId"):
                        child_ids.append(item["agentThreadId"])
            agents = []
            for child in dict.fromkeys(child_ids):
                child_thread = read_thread_compat(client, child)
                if child_thread.get("parentThreadId") == root_thread:
                    agents.append(self._agent_summary(child_thread))
        return {"count": len(agents), "agents": agents}

    def _agent_summary(self, thread: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": thread["id"],
            "nickname": thread.get("agentNickname"),
            "role": thread.get("agentRole"),
            "status": _enum(thread.get("status")),
            "parent_thread_id": thread.get("parentThreadId"),
        }

    def delegate(self, message: str, **options: Any) -> dict[str, Any]:
        prompt = (
            "Delegate this work using native Codex subagents when useful. "
            "Preserve child ownership and synthesize their results.\n\n" + message
        )
        return self.start_task(prompt, **options)

    def dashboard(self) -> dict[str, Any]:
        tasks = (
            self.list_tasks(limit=10) if self.capabilities.codex_path else {"count": 0, "tasks": []}
        )
        workers = self.list_workers()
        return {
            "workspace": str(self.cwd),
            "runtime": {
                "status": self.capabilities.daemon_state,
                "transport": (
                    "managed-proxy"
                    if self.capabilities.daemon_state == "healthy"
                    and self.capabilities.shared_transport_available
                    else "direct-fallback"
                ),
            },
            "tasks": tasks["tasks"],
            "workers": workers["workers"],
        }

    def _active_turn(self, thread_id: str) -> str:
        turn_id = self.store.active_turn(thread_id)
        metadata = self.store.worker(thread_id) or self.store.task(thread_id) or {}
        if turn_id:
            metadata = self._reconcile_active(thread_id, metadata)
            turn_id = self.store.active_turn(thread_id)
        if not turn_id:
            raise AxiError(
                "stale_active_turn",
                f"No exact active turn is recorded for {thread_id}.",
                f"Run `codex-axi task view {thread_id}` before retrying.",
            )
        return turn_id

    def _reconcile_active(self, thread_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
        turn_id = self.store.active_turn(thread_id)
        owner_pid = metadata.get("owner_pid") or metadata.get("pid")
        try:
            with self.client() as client:
                thread = read_thread_compat(client, thread_id)
        except AxiError:
            if owner_pid and not _pid_alive(owner_pid):
                return self._finish_reconciliation(thread_id, metadata, "interrupted")
            return metadata
        matching = next(
            (turn for turn in thread.get("turns", []) if turn.get("id") == turn_id), None
        )
        status = matching and _enum(matching.get("status"))
        if status in {"completed", "failed", "interrupted", "cancelled"}:
            return self._finish_reconciliation(thread_id, metadata, status)
        if owner_pid and not _pid_alive(owner_pid):
            return self._finish_reconciliation(thread_id, metadata, "interrupted")
        return metadata

    def _finish_reconciliation(
        self, thread_id: str, metadata: dict[str, Any], status: str
    ) -> dict[str, Any]:
        self.store.set_active_turn(thread_id, None)
        values = {"status": status, "active_turn_id": None, "owner_pid": None}
        if self.store.worker(thread_id):
            return self.store.update_worker(thread_id, **values)
        return self.store.update_task(thread_id, **values)

    def _send_control(
        self, thread_id: str, action: str, message: str | None = None, *, timeout: float = 5
    ) -> None:
        control_id = self.store.enqueue_control(thread_id, action, message)
        deadline = time.monotonic() + timeout if timeout else None
        while deadline is None or time.monotonic() < deadline:
            result = self.store.control_result(control_id)
            if result:
                if result["status"] == "applied":
                    return
                raise AxiError(
                    "control_rejected",
                    f"Active turn rejected {action}.",
                    f"Run `codex-axi task view {thread_id}` and retry with current state.",
                )
            time.sleep(0.05)
        raise AxiError(
            "stale_active_turn",
            f"Active turn {self.store.active_turn(thread_id)} did not acknowledge {action}.",
            f"Run `codex-axi task view {thread_id}` before retrying.",
        )

    def _run_controlled(self, thread_id: str, turn: Any, *, timeout: float = 0) -> Any:
        stop = threading.Event()

        def relay() -> None:
            while not stop.wait(0.05):
                for control in self.store.take_controls(thread_id):
                    try:
                        if control["action"] == "steer":
                            turn.steer(control["message"])
                        elif control["action"] == "interrupt":
                            turn.interrupt()
                        else:
                            raise ValueError("unknown control action")
                        self.store.finish_control(control["id"], status="applied")
                    except Exception as error:
                        self.store.finish_control(
                            control["id"], status="rejected", error=type(error).__name__
                        )

        thread = threading.Thread(target=relay, name=f"codex-axi-control-{turn.id}", daemon=True)
        thread.start()
        completed = threading.Event()
        outcome: dict[str, Any] = {}

        def collect() -> None:
            try:
                outcome["result"] = self._collect_turn(thread_id, turn)
            except BaseException as error:
                outcome["error"] = error
            finally:
                completed.set()

        collector = threading.Thread(target=collect, name=f"codex-axi-turn-{turn.id}", daemon=True)
        collector.start()
        try:
            if not completed.wait(timeout if timeout > 0 else None):
                try:
                    turn.interrupt()
                except Exception as error:
                    raise AxiError(
                        "turn_timeout",
                        f"Task {thread_id} exceeded {timeout:g} seconds and could not be "
                        "interrupted.",
                        f"Run `codex-axi task view {thread_id}` before retrying.",
                    ) from error
                raise AxiError(
                    "turn_timeout",
                    f"Task {thread_id} exceeded {timeout:g} seconds and was interrupted.",
                    f"Run `codex-axi task view {thread_id}` before retrying.",
                )
            if "error" in outcome:
                raise outcome["error"]
            return outcome["result"]
        finally:
            stop.set()
            thread.join(timeout=1)

    def _collect_turn(self, thread_id: str, turn: Any) -> Any:
        from openai_codex import TurnResult

        completed = None
        items = []
        usage = None
        for event in turn.stream():
            payload = event.payload
            if event.method == "turn/started" and getattr(payload, "turn", None):
                started_id = payload.turn.id
                if started_id != turn.id:
                    raise AxiError(
                        "turn_id_mismatch",
                        "Codex reported a different active turn identifier.",
                        f"Run `codex-axi task view {thread_id}` before retrying control.",
                    )
                self.store.set_active_turn(thread_id, started_id)
            elif event.method == "item/completed" and getattr(payload, "turn_id", None) == turn.id:
                items.append(payload.item)
            elif (
                event.method == "thread/tokenUsage/updated"
                and getattr(payload, "turn_id", None) == turn.id
            ):
                usage = payload.token_usage
            elif event.method == "turn/completed" and getattr(payload, "turn", None):
                if payload.turn.id == turn.id:
                    completed = payload.turn
        if completed is None:
            raise RuntimeError("turn completed event not received")
        if _enum(completed.status) == "failed":
            message = getattr(completed.error, "message", None) or "turn failed"
            raise RuntimeError(message)
        return TurnResult(
            id=completed.id,
            status=completed.status,
            error=completed.error,
            started_at=completed.started_at,
            completed_at=completed.completed_at,
            duration_ms=completed.duration_ms,
            final_response=_final_response_from_items(items),
            items=items,
            usage=usage,
        )

    def _start_thread(self, client: Any, **options: Any) -> Any:
        return client.thread_start(
            **self._lifecycle_options(options),
            developer_instructions=options.get("developer_instructions"),
        )

    def _lifecycle_options(self, options: dict[str, Any]) -> dict[str, Any]:
        from openai_codex import ApprovalMode, Sandbox

        sandbox = {
            "read-only": Sandbox.read_only,
            "workspace-write": Sandbox.workspace_write,
            "full-access": Sandbox.full_access,
        }[options.get("sandbox", "workspace-write")]
        approval = {"auto-review": ApprovalMode.auto_review, "deny-all": ApprovalMode.deny_all}[
            options.get("approval", "auto-review")
        ]
        return {
            "cwd": str(options.get("cwd") or self.cwd),
            "model": options.get("model"),
            "sandbox": sandbox,
            "approval_mode": approval,
        }

    def _turn_options(self, options: dict[str, Any]) -> dict[str, Any]:
        result = self._lifecycle_options(options)
        if options.get("effort"):
            result["effort"] = options["effort"]
        return result

    def _thread_summary(self, thread: Any) -> dict[str, Any]:
        data = model_dict(thread)
        metadata = self.store.task(data["id"]) or self.store.worker(data["id"]) or {}
        return {
            "id": data["id"],
            "name": data.get("name") or data.get("preview", "")[:80],
            "status": metadata.get("status", _enum(data.get("status"))),
            "parent_thread_id": data.get("parent_thread_id"),
        }

    def _result(
        self, thread_id: str, result: Any, *, kind: str = "task", full: bool = False
    ) -> dict[str, Any]:
        response = result.final_response or ""
        shown, total = preview(response, limit=10**9 if full else 800)
        document = {
            kind: {
                "id": thread_id,
                "turn_id": result.id,
                "status": _enum(result.status),
                "final_response": shown,
                "duration_ms": result.duration_ms,
            }
        }
        if total is not None:
            document[kind]["final_response_chars"] = total
            document["help"] = [f"codex-axi {kind} view {thread_id} --full"]
        return document


def _enum(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"type"}:
        return value["type"]
    return getattr(value, "value", value)


def _interruption_status(error: BaseException) -> str:
    if isinstance(error, (KeyboardInterrupt, AxiError)) and (
        isinstance(error, KeyboardInterrupt) or error.code == "turn_timeout"
    ):
        return "interrupted"
    return "failed"


def _latest(thread: dict[str, Any], field: str) -> Any:
    turns = thread.get("turns", [])
    return turns[-1].get(field) if turns else None


def _last_response(thread: dict[str, Any]) -> str:
    for turn in reversed(thread.get("turns", [])):
        for item in reversed(turn.get("items", [])):
            if item.get("type") == "agentMessage" and item.get("text"):
                return item["text"]
    return ""


def _final_response_from_items(items: list[Any]) -> str | None:
    fallback = None
    for item in reversed(items):
        value = item.root if hasattr(item, "root") else item
        if getattr(value, "type", None) != "agentMessage":
            continue
        phase = _enum(getattr(value, "phase", None))
        if phase == "final_answer":
            return value.text
        if phase is None and fallback is None:
            fallback = value.text
    return fallback


def _worker_instructions(role: str | None) -> str:
    identity = f" Your assigned role is {role}." if role else ""
    return "You are an AXI-managed worker thread, not a native Codex subagent." + identity


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
