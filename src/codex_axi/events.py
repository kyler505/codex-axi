"""Passive, local event journals for opt-in turn observability."""

from __future__ import annotations

import json
import os
import time
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

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


class EventJournal:
    """Append and read one turn's newline-delimited JSON event stream."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._sequence = 0

    @classmethod
    def create(cls, state_path: Path, thread_id: str, turn_id: str) -> EventJournal:
        directory = state_path.parent / "events"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{thread_id}.{turn_id}.jsonl"
        path.write_text("")
        os.chmod(path, 0o600)
        return cls(path)

    def emit(self, event: Any) -> None:
        """Append an allow-listed event; observability must never break a turn."""

        if event.method not in VISIBLE_EVENT_METHODS:
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
    try:
        records = [_decode_record(line) for line in path.read_text().splitlines() if line.strip()]
    except FileNotFoundError as error:
        raise AxiError(
            "events_unavailable",
            "The event journal is no longer available.",
            "Start a new turn with `--events` to capture live events.",
        ) from error
    return [record for record in records if record.get("sequence", 0) > since][-limit:]


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


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dict__"):
        return vars(value)
    return str(value)


def follow_events(
    path: Path, *, since: int = 0, running: Any, poll_interval: float = 0.1
) -> Iterator[dict[str, Any]]:
    """Yield new records until the owning turn is terminal and the journal is drained."""

    position = 0
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
                if not running():
                    # Check once more after observing terminal metadata.
                    handle.seek(position)
                    line = handle.readline()
                    if not line:
                        return
                    position = handle.tell()
                    record = _decode_record(line)
                    if record.get("sequence", 0) > since:
                        yield record
                    continue
                time.sleep(poll_interval)
    except FileNotFoundError as error:
        raise AxiError(
            "events_unavailable",
            "The event journal is no longer available.",
            "Start a new turn with `--events` to capture live events.",
        ) from error
