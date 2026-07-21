"""Minimal codex-axi-owned metadata; Codex remains authoritative for threads."""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .errors import AxiError
from .locking import file_lock

DEFAULT_RETENTION_DAYS = 30


class StateStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(
            os.environ.get("CODEX_AXI_STATE", Path.home() / ".codex-axi" / "state.json")
        )

    def read(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text())
        except FileNotFoundError:
            return {"version": 1, "workers": {}, "active_turns": {}}
        except json.JSONDecodeError:
            corrupt = self.path.with_name(f"{self.path.name}.corrupt.{int(time.time())}")
            os.replace(self.path, corrupt)
            return {"version": 1, "workers": {}, "active_turns": {}}
        except OSError as error:
            raise AxiError(
                "state_unavailable",
                "codex-axi state could not be read.",
                f"Check permissions for `{self.path}` and retry.",
            ) from error

    def worker(self, thread_id: str) -> dict[str, Any] | None:
        return self.read().get("workers", {}).get(thread_id)

    def task(self, thread_id: str) -> dict[str, Any] | None:
        return self.read().get("tasks", {}).get(thread_id)

    def workers(self) -> dict[str, dict[str, Any]]:
        return self.read().get("workers", {})

    def active_turn(self, thread_id: str) -> str | None:
        return self.read().get("active_turns", {}).get(thread_id)

    def set_active_turn(self, thread_id: str, turn_id: str | None) -> None:
        with self._locked() as data:
            turns = data.setdefault("active_turns", {})
            if turn_id is None:
                turns.pop(thread_id, None)
            else:
                turns[thread_id] = turn_id
            self._write(data)

    def enqueue_control(self, thread_id: str, action: str, message: str | None = None) -> str:
        control_id = str(uuid.uuid4())
        with self._locked() as data:
            data.setdefault("controls", {}).setdefault(thread_id, []).append(
                {"id": control_id, "action": action, "message": message, "created_at": time.time()}
            )
            self._write(data)
        return control_id

    def take_controls(self, thread_id: str) -> list[dict[str, Any]]:
        with self._locked() as data:
            controls = data.setdefault("controls", {}).pop(thread_id, [])
            if controls:
                self._write(data)
            return controls

    def finish_control(
        self,
        control_id: str,
        *,
        status: str,
        error: str | None = None,
        thread_id: str | None = None,
    ) -> None:
        with self._locked() as data:
            data.setdefault("control_results", {})[control_id] = {
                "status": status,
                "error": error,
                "created_at": time.time(),
                "thread_id": thread_id,
            }
            self._write(data)

    def control_result(self, control_id: str) -> dict[str, Any] | None:
        with self._locked() as data:
            result = data.setdefault("control_results", {}).pop(control_id, None)
            if result is not None:
                self._write(data)
            return result

    def update_worker(self, thread_id: str, **values: Any) -> dict[str, Any]:
        with self._locked() as data:
            worker = data.setdefault("workers", {}).setdefault(thread_id, {})
            worker.update(values)
            self._write(data)
            return worker.copy()

    def update_task(self, thread_id: str, **values: Any) -> dict[str, Any]:
        with self._locked() as data:
            task = data.setdefault("tasks", {}).setdefault(thread_id, {})
            task.update(values)
            self._write(data)
            return task.copy()

    def remove_worker(self, thread_id: str) -> bool:
        with self._locked() as data:
            removed = data.setdefault("workers", {}).pop(thread_id, None) is not None
            if removed:
                self._write(data)
            return removed

    def remove_task(self, thread_id: str) -> bool:
        with self._locked() as data:
            removed = data.setdefault("tasks", {}).pop(thread_id, None) is not None
            if removed:
                self._write(data)
            return removed

    def retention_summary(self, *, warning_threshold: int = 100) -> dict[str, Any]:
        data = self.read()
        controls = sum(len(items) for items in data.get("controls", {}).values())
        results = len(data.get("control_results", {}))
        journals = sum(
            bool(item.get("event_log"))
            for group in ("tasks", "workers")
            for item in data.get(group, {}).values()
        )
        retained = controls + results + journals
        return {
            "retained": retained,
            "controls": controls,
            "control_results": results,
            "event_journals": journals,
            "warning": retained >= warning_threshold,
        }

    def cleanup(
        self,
        *,
        retention_days: float = DEFAULT_RETENTION_DAYS,
        workspace: Path | None = None,
        dry_run: bool = False,
        now: float | None = None,
    ) -> dict[str, Any]:
        cutoff = (time.time() if now is None else now) - retention_days * 86400
        workspace = workspace.resolve() if workspace else None
        removed = {"controls": 0, "control_results": 0, "event_journals": 0, "metadata": 0}
        with self._locked() as data:
            active = data.get("active_turns", {})
            scoped_threads = {
                thread_id
                for group in ("tasks", "workers")
                for thread_id, item in data.get(group, {}).items()
                if workspace is None or Path(item.get("cwd", "")).resolve() == workspace
            }
            for thread_id, controls in list(data.get("controls", {}).items()):
                if thread_id not in scoped_threads or thread_id in active:
                    continue
                kept = [item for item in controls if item.get("created_at", cutoff + 1) >= cutoff]
                removed["controls"] += len(controls) - len(kept)
                if not dry_run:
                    if kept:
                        data["controls"][thread_id] = kept
                    else:
                        data["controls"].pop(thread_id, None)
            for control_id, result in list(data.get("control_results", {}).items()):
                result_thread = result.get("thread_id")
                if workspace is not None and result_thread not in scoped_threads:
                    continue
                if result.get("created_at", cutoff + 1) < cutoff:
                    removed["control_results"] += 1
                    if not dry_run:
                        data["control_results"].pop(control_id, None)
            for group in ("tasks", "workers"):
                for thread_id, item in list(data.get(group, {}).items()):
                    if thread_id not in scoped_threads or thread_id in active:
                        continue
                    event_path = item.get("event_log")
                    if event_path:
                        path = Path(event_path)
                        try:
                            stale = path.stat().st_mtime < cutoff
                        except OSError:
                            stale = True
                        from .events import EventJournal

                        journal = EventJournal(path)
                        if stale and not journal.is_writer_active():
                            removed["event_journals"] += int(path.exists())
                            removed["metadata"] += int(not path.exists())
                            if not dry_run:
                                path.unlink(missing_ok=True)
                                journal.finished_path.unlink(missing_ok=True)
                                journal.writer_path.unlink(missing_ok=True)
                                item["event_log"] = None
                                item["event_turn_id"] = None
            if not dry_run and any(removed.values()):
                self._write(data)
        return {
            "cleanup": {
                "dry_run": dry_run,
                "retention_days": retention_days,
                "workspace": str(workspace) if workspace else None,
                "removed": removed,
                "total": sum(removed.values()),
                "status": (
                    "no_op"
                    if not any(removed.values())
                    else "would_remove"
                    if dry_run
                    else "removed"
                ),
            }
        }

    @contextmanager
    def _locked(self):
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+") as lock:
            with file_lock(lock):
                yield self.read()

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self.path.parent, prefix="state.", suffix=".json")
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.path)
            if os.name != "nt":
                os.chmod(self.path, 0o600)
        finally:
            try:
                os.unlink(name)
            except FileNotFoundError:
                pass
