"""Passive, local event journals for opt-in turn observability."""

from __future__ import annotations

import json
import os
import time
from collections import deque
from collections.abc import Callable, Iterator
from enum import Enum
from pathlib import Path
from typing import Any

from .errors import AxiError

VISIBLE_EVENT_METHODS = {
    "error",
    "item/agentMessage/delta",
    "item/commandExecution/outputDelta",
    "item/completed",
    "item/fileChange/outputDelta",
    "item/fileChange/patchUpdated",
    "item/mcpToolCall/progress",
    "item/plan/delta",
    "item/started",
    "turn/completed",
    "turn/plan/updated",
    "turn/started",
    "warning",
}
EVENT_SCHEMA_VERSION = 1
MAX_EVENT_BYTES = 64 * 1024
TERMINAL_DRAIN_SECONDS = 2.0


class EventJournal:
    """Append and read one turn's newline-delimited JSON event stream."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._sequence = 0

    @property
    def finished_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".finished")

    @property
    def writer_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".writer")

    @classmethod
    def create(cls, state_path: Path, thread_id: str, turn_id: str) -> EventJournal:
        directory = state_path.parent / "events"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{thread_id}.{turn_id}.jsonl"
        _write_private_file(path)
        journal = cls(path)
        journal.finished_path.unlink(missing_ok=True)
        _write_private_file(journal.writer_path, str(os.getpid()).encode())
        return journal

    def finish(self) -> None:
        """Mark the owning stream drained without affecting turn completion."""

        try:
            _write_private_file(self.finished_path)
            self.writer_path.unlink(missing_ok=True)
        except Exception:
            return

    def is_finished(self) -> bool:
        return self.finished_path.exists()

    def is_writer_active(self) -> bool:
        try:
            writer_pid = int(self.writer_path.read_text())
            os.kill(writer_pid, 0)
            return True
        except PermissionError:
            return True
        except (OSError, ValueError):
            return False

    def emit(self, event: Any) -> None:
        """Append an allow-listed event; observability must never break a turn."""

        if event.method not in VISIBLE_EVENT_METHODS:
            return
        if event.method in ("item/started", "item/completed") and _is_reasoning_item(event.payload):
            return
        try:
            self._sequence += 1
            payload = event.payload
            if hasattr(payload, "model_dump"):
                payload = payload.model_dump(mode="json", by_alias=True)
            elif not isinstance(payload, dict):
                payload = vars(payload)
            record = {
                "schema_version": EVENT_SCHEMA_VERSION,
                "sequence": self._sequence,
                "method": event.method,
                "payload": payload,
            }
            encoded = json.dumps(record, separators=(",", ":"), default=_json_value)
            if len(encoded.encode("utf-8")) > MAX_EVENT_BYTES:
                record["payload"] = {
                    "truncated": True,
                    "original_bytes": len(encoded.encode("utf-8")),
                }
                encoded = json.dumps(record, separators=(",", ":"))
            with self.path.open("a") as handle:
                handle.write(encoded + "\n")
                handle.flush()
        except Exception:
            # Event capture is a passive tap. Runtime completion and control are authoritative.
            return


def read_events(path: Path, *, since: int = 0, limit: int = 100) -> list[dict[str, Any]]:
    records, _ = read_event_page(path, since=since, limit=limit)
    return records


def read_event_page(
    path: Path, *, since: int = 0, limit: int = 100
) -> tuple[list[dict[str, Any]], int]:
    records: deque[dict[str, Any]] = deque(maxlen=limit)
    total = 0
    try:
        with path.open() as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = _decode_record(line)
                if record.get("sequence", 0) <= since:
                    continue
                total += 1
                records.append(record)
    except FileNotFoundError as error:
        raise AxiError(
            "events_unavailable",
            "The event journal is no longer available.",
            "Start a new turn with `--events` to capture live events.",
        ) from error
    return list(records), total


def _decode_record(line: str) -> dict[str, Any]:
    try:
        record = json.loads(line)
    except json.JSONDecodeError as error:
        raise AxiError(
            "events_corrupt",
            "The event journal contains an incomplete or invalid record.",
            "Retry after the owning turn writes the next complete event.",
        ) from error
    if not isinstance(record, dict) or not isinstance(record.get("sequence"), int):
        raise AxiError(
            "events_corrupt",
            "The event journal contains an invalid event envelope.",
            "Start a new turn with `--events` to create a fresh journal.",
        )
    return record


def _is_reasoning_item(payload: Any) -> bool:
    item = payload.get("item") if isinstance(payload, dict) else getattr(payload, "item", None)
    if item is None:
        return False
    item_type = item.get("type") if isinstance(item, dict) else getattr(item, "type", None)
    if isinstance(item_type, Enum):
        item_type = item_type.value
    return item_type == "reasoning"


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dict__"):
        return vars(value)
    return str(value)


def _write_private_file(path: Path, contents: bytes = b"") -> None:
    fd = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    try:
        if contents:
            os.write(fd, contents)
    finally:
        os.close(fd)


def follow_events(
    path: Path,
    *,
    since: int = 0,
    running: Callable[[], bool],
    finished: Callable[[], bool],
    writer_active: Callable[[], bool],
    poll_interval: float = 0.1,
    terminal_drain: float = TERMINAL_DRAIN_SECONDS,
) -> Iterator[dict[str, Any]]:
    """Yield new records until the owning turn is terminal and the journal is drained."""

    position = 0
    terminal_since = None
    try:
        with path.open() as handle:
            while True:
                handle.seek(position)
                line = handle.readline()
                if line:
                    position = handle.tell()
                    record = _decode_record(line)
                    if record.get("sequence", 0) > since:
                        yield record
                    continue
                if finished():
                    return
                if running() or writer_active():
                    terminal_since = None
                elif terminal_since is None:
                    terminal_since = time.monotonic()
                elif time.monotonic() - terminal_since >= terminal_drain:
                    return
                time.sleep(poll_interval)
    except FileNotFoundError as error:
        raise AxiError(
            "events_unavailable",
            "The event journal is no longer available.",
            "Start a new turn with `--events` to capture live events.",
        ) from error
