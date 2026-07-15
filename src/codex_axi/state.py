"""Minimal codex-axi-owned metadata; Codex remains authoritative for threads."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .errors import AxiError


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
                {"id": control_id, "action": action, "message": message}
            )
            self._write(data)
        return control_id

    def take_controls(self, thread_id: str) -> list[dict[str, Any]]:
        with self._locked() as data:
            controls = data.setdefault("controls", {}).pop(thread_id, [])
            if controls:
                self._write(data)
            return controls

    def finish_control(self, control_id: str, *, status: str, error: str | None = None) -> None:
        with self._locked() as data:
            data.setdefault("control_results", {})[control_id] = {
                "status": status,
                "error": error,
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

    @contextmanager
    def _locked(self):
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield self.read()
            fcntl.flock(lock, fcntl.LOCK_UN)

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self.path.parent, prefix="state.", suffix=".json")
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(name, self.path)
        finally:
            try:
                os.unlink(name)
            except FileNotFoundError:
                pass
