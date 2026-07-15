import json
import shutil
import subprocess

import pytest


def test_installed_runtime_exposes_required_protocol_methods(tmp_path):
    codex = shutil.which("codex")
    if not codex:
        pytest.skip("Codex is not installed")
    subprocess.run(
        [codex, "app-server", "generate-json-schema", "--out", str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    requests = json.loads((tmp_path / "ClientRequest.json").read_text())
    methods = {variant["properties"]["method"]["enum"][0] for variant in requests["oneOf"]}
    for method in (
        "initialize",
        "thread/list",
        "thread/read",
        "thread/start",
        "thread/resume",
        "thread/archive",
        "turn/start",
        "turn/steer",
        "turn/interrupt",
    ):
        assert method in methods
    steer = json.loads((tmp_path / "v2" / "TurnSteerParams.json").read_text())
    assert set(steer["required"]) == {"threadId", "expectedTurnId", "input"}
    initialize = json.loads((tmp_path / "v1" / "InitializeParams.json").read_text())
    assert initialize["required"] == ["clientInfo"]
    notifications = (tmp_path / "ServerNotification.json").read_text()
    assert '"turn/started"' in notifications
    assert '"subAgentActivity"' in notifications
