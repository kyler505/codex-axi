import json
import shutil
import subprocess
from pathlib import Path

import pytest

from codex_axi import integrations
from codex_axi.errors import AxiError


def test_setup_hook_is_idempotent_and_repairs_command(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(integrations, "_command", lambda: "/new/codex-axi")
    first = integrations.setup_hooks("claude")
    second = integrations.setup_hooks("claude")
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert first["setup"]["status"] == "updated"
    assert second["setup"]["status"] == "no_op"
    assert settings["hooks"]["SessionStart"] == [
        {
            "matcher": "",
            "hooks": [{"type": "command", "command": "/new/codex-axi"}],
        }
    ]


def test_codex_and_opencode_integrations_are_generated(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(integrations, "_command", lambda: "codex-axi")
    integrations.setup_hooks("codex")
    integrations.setup_hooks("opencode")
    assert "hooks = true" in (tmp_path / ".codex" / "config.toml").read_text()
    hooks = json.loads((tmp_path / ".codex" / "hooks.json").read_text())
    assert hooks["hooks"]["SessionStart"][0]["hooks"][0] == {
        "type": "command",
        "command": "codex-axi",
    }
    assert (
        "codex-axi" in (tmp_path / ".config" / "opencode" / "plugins" / "codex-axi.js").read_text()
    )
    node = shutil.which("node")
    if node:
        subprocess.run(
            [
                node,
                "--check",
                str(tmp_path / ".config" / "opencode" / "plugins" / "codex-axi.js"),
            ],
            check=True,
            capture_output=True,
            text=True,
        )


def test_setup_preserves_unrelated_hooks(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(integrations, "_command", lambda: "codex-axi")
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "startup",
                            "hooks": [{"type": "command", "command": "other-tool"}],
                        }
                    ]
                },
                "theme": "dark",
            }
        )
    )

    integrations.setup_hooks("claude")

    settings = json.loads(path.read_text())
    assert settings["theme"] == "dark"
    assert settings["hooks"]["SessionStart"][0]["hooks"][0]["command"] == "other-tool"


def test_setup_refuses_to_overwrite_malformed_config(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text("{broken")

    with pytest.raises(AxiError, match="malformed JSON"):
        integrations.setup_hooks("claude")

    assert path.read_text() == "{broken"


def test_setup_enables_existing_disabled_codex_feature(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(integrations, "_command", lambda: "codex-axi")
    path = tmp_path / ".codex" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text("[features]\nhooks = false\n")

    integrations.setup_hooks("codex")

    assert path.read_text() == "[features]\nhooks = true\n"
