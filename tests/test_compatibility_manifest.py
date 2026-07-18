import json
from pathlib import Path
from types import SimpleNamespace

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10
    import tomli as tomllib

from codex_axi.events import EventJournal, read_events
from codex_axi.integrations import ADAPTER_VERSIONS
from codex_axi.runtime import SUPPORTED_CODEX, read_thread_compat

ROOT = Path(__file__).parents[1]


def test_compatibility_manifest_matches_runtime_policy_and_fixtures():
    manifest = json.loads((ROOT / "compatibility" / "manifest.json").read_text())
    assert manifest["schema_version"] == 1
    assert manifest["codex"][0]["cli"] == SUPPORTED_CODEX
    assert manifest["integrations"] == ADAPTER_VERSIONS
    for name, version in ADAPTER_VERSIONS.items():
        assert (ROOT / "compatibility" / "integrations" / f"{name}-v{version}.json").exists()
    for entry in manifest["codex"]:
        assert entry["evidence"] in {"tested", "fixture-tested", "degraded", "unsupported"}
        for fixture in entry["fixtures"]:
            data = json.loads((ROOT / "compatibility" / "fixtures" / fixture).read_text())
            assert data["metadata"]["sanitized"] is True
            assert data["metadata"]["execution_path"] in entry["paths"]
            assert "futureAdditiveField" in data["thread_read"]["thread"]
            assert {
                "initialize",
                "daemon_version",
                "thread_read",
                "events",
                "native_agent",
                "rate_limits",
                "failures",
            } <= set(data)

    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    sdk_requirement = next(
        item for item in project["project"]["dependencies"] if item.startswith("openai-codex")
    )
    assert sdk_requirement.removeprefix("openai-codex") == manifest["codex"][0]["sdk"]


def test_manifest_covers_declared_python_and_platform_targets():
    manifest = json.loads((ROOT / "compatibility" / "manifest.json").read_text())
    assert manifest["python"] == ["3.10", "3.11", "3.12", "3.13", "3.14"]
    assert set(manifest["platforms"]) == {"macos", "linux", "windows"}


def test_protocol_fixture_drives_thread_and_event_compatibility(tmp_path):
    fixture = json.loads(
        (ROOT / "compatibility" / "fixtures" / "codex-0.144-sdk-0.144.4.json").read_text()
    )

    class RawClient:
        class _client:
            @staticmethod
            def _request_raw(method, params):
                assert method == "thread/read"
                assert params == {"threadId": "thread-fixture", "includeTurns": True}
                return fixture["thread_read"]

    thread = read_thread_compat(RawClient(), "thread-fixture")
    assert thread["futureAdditiveField"] == {"preserved": True}

    journal = EventJournal.create(tmp_path / "state.json", "thread-fixture", "turn-fixture")
    for item in fixture["events"]:
        journal.emit(SimpleNamespace(method=item["method"], payload=item["payload"]))
    records = read_events(journal.path)
    assert [record["method"] for record in records] == [
        "turn/started",
        "future/additiveEvent",
        "turn/completed",
    ]
    assert records[1]["extension"] is True
