import json
import sys
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
    journal.emit(event("future/additiveEvent", value="unvetted-secret"))

    records = read_events(journal.path)
    assert [record["sequence"] for record in records] == [1, 2, 3]
    assert all(record["schema_version"] == EVENT_SCHEMA_VERSION for record in records)
    assert [record["method"] for record in records] == [
        "turn/started",
        "item/commandExecution/outputDelta",
        "future/additiveEvent",
    ]
    assert records[-1]["extension"] is True
    assert records[-1]["payload"] == {"omitted": True}
    assert "private" not in journal.path.read_text()
    assert "unvetted-secret" not in journal.path.read_text()
    if sys.platform != "win32":
        assert journal.path.stat().st_mode & 0o777 == 0o600


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
            writer_active=journal.is_writer_active,
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

    writer = threading.Thread(target=finish_later, daemon=True)
    writer.start()
    records = list(
        follow_events(
            journal.path,
            running=lambda: False,
            finished=journal.is_finished,
            writer_active=journal.is_writer_active,
            poll_interval=0.01,
            terminal_drain=0.01,
        )
    )
    writer.join()

    assert [record["method"] for record in records] == ["turn/completed"]
    assert not journal.writer_path.exists()


def test_follow_events_uses_bounded_fallback_after_writer_exits(tmp_path):
    journal = EventJournal.create(tmp_path / "state.json", "thread-1", "turn-1")
    journal.writer_path.unlink()

    started = time.monotonic()
    records = list(
        follow_events(
            journal.path,
            running=lambda: False,
            finished=journal.is_finished,
            writer_active=journal.is_writer_active,
            poll_interval=0.005,
            terminal_drain=0.02,
        )
    )

    assert records == []
    assert time.monotonic() - started >= 0.02


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


def test_follow_rejects_terminal_partial_record(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text('{"schema_version":1,"sequence":1')
    with pytest.raises(AxiError) as caught:
        list(
            follow_events(
                path,
                running=lambda: False,
                finished=lambda: True,
                writer_active=lambda: False,
            )
        )
    assert caught.value.code == "events_corrupt"


def test_snapshot_rejects_active_writer_partial_tail(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text(
        '{"schema_version":1,"sequence":1,"method":"turn/started","payload":{}}\n'
        '{"schema_version":1,"sequence":2'
    )
    with pytest.raises(AxiError) as caught:
        read_events(path)
    assert caught.value.code == "events_corrupt"
