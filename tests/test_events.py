import json
import threading
import time
from types import SimpleNamespace

import pytest

from codex_axi.errors import AxiError
from codex_axi.events import (
    EVENT_SCHEMA_VERSION,
    MAX_EVENT_BYTES,
    EventJournal,
    follow_events,
    read_event_page,
    read_events,
)


def event(method, **payload):
    return SimpleNamespace(method=method, payload=SimpleNamespace(**payload))


def test_journal_captures_allowlisted_events_and_ignores_reasoning(tmp_path):
    journal = EventJournal.create(tmp_path / "state.json", "thread-1", "turn-1")

    journal.emit(event("turn/started", turn={"id": "turn-1"}))
    journal.emit(event("item/reasoning/textDelta", delta="private"))
    journal.emit(event("item/commandExecution/outputDelta", delta="progress"))

    records = read_events(journal.path)
    assert [record["sequence"] for record in records] == [1, 2]
    assert all(record["schema_version"] == EVENT_SCHEMA_VERSION for record in records)


def test_journal_excludes_reasoning_items_from_generic_envelopes(tmp_path):
    journal = EventJournal.create(tmp_path / "state.json", "thread-1", "turn-1")
    secret = "Contemplating delay options"

    journal.emit(event("item/started", item={"type": "reasoning", "text": secret}))
    journal.emit(event("item/completed", item={"type": "reasoning", "text": secret}))
    journal.emit(event("item/completed", item={"type": "message", "text": "visible"}))

    contents = journal.path.read_text()
    assert secret not in contents

    records = read_events(journal.path)
    assert [record["sequence"] for record in records] == [1]
    assert records[0]["payload"]["item"]["type"] == "message"
    assert "private" not in journal.path.read_text()
    assert journal.path.stat().st_mode & 0o777 == 0o600


def test_read_events_supports_cursor_and_limit(tmp_path):
    journal = EventJournal.create(tmp_path / "state.json", "thread-1", "turn-1")
    for number in range(4):
        journal.emit(event("item/agentMessage/delta", delta=str(number)))

    records = read_events(journal.path, since=1, limit=2)
    assert [record["sequence"] for record in records] == [3, 4]


def test_event_page_scans_incrementally_with_bounded_tail(tmp_path, monkeypatch):
    journal = EventJournal.create(tmp_path / "state.json", "thread-1", "turn-1")
    for number in range(10):
        journal.emit(event("item/agentMessage/delta", delta=str(number)))
    monkeypatch.setattr(
        type(journal.path),
        "read_text",
        lambda _path: pytest.fail("snapshot must not load the whole journal"),
    )

    records, total = read_event_page(journal.path, since=2, limit=2)
    assert total == 8
    assert [record["sequence"] for record in records] == [9, 10]


def test_follow_events_drains_terminal_journal(tmp_path):
    journal = EventJournal.create(tmp_path / "state.json", "thread-1", "turn-1")
    journal.emit(event("turn/completed", turn={"id": "turn-1"}))

    journal.finish()
    records = list(
        follow_events(
            journal.path,
            running=lambda: False,
            finished=journal.is_finished,
        )
    )
    assert len(records) == 1
    assert json.loads(journal.path.read_text())["method"] == "turn/completed"


def test_follow_events_waits_for_writer_after_metadata_is_terminal(tmp_path):
    journal = EventJournal.create(tmp_path / "state.json", "thread-1", "turn-1")

    def finish_later():
        time.sleep(0.05)
        journal.emit(event("turn/completed", turn={"id": "turn-1"}))
        journal.finish()

    writer = threading.Thread(target=finish_later)
    writer.start()
    records = list(
        follow_events(
            journal.path,
            running=lambda: False,
            finished=journal.is_finished,
            poll_interval=0.01,
            terminal_drain=0.2,
        )
    )
    writer.join()

    assert [record["method"] for record in records] == ["turn/completed"]


def test_event_payload_is_bounded(tmp_path):
    journal = EventJournal.create(tmp_path / "state.json", "thread-1", "turn-1")
    journal.emit(event("item/commandExecution/outputDelta", delta="x" * MAX_EVENT_BYTES))
    record = read_events(journal.path)[0]
    assert record["payload"]["truncated"] is True
    assert record["payload"]["original_bytes"] > MAX_EVENT_BYTES


def test_corrupt_event_record_is_structured(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text("{partial")
    with pytest.raises(AxiError) as caught:
        read_events(path)
    assert caught.value.code == "events_corrupt"
