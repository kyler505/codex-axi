import json
import shutil
import subprocess
from pathlib import Path

import pytest

from codex_axi import integrations
from codex_axi.errors import AxiError

ROOT = Path(__file__).parents[1]


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
    expected = json.loads((ROOT / "compatibility" / "integrations" / "claude-v1.json").read_text())
    expected["hooks"]["SessionStart"][0]["hooks"][0]["command"] = "/new/codex-axi"
    assert settings == expected


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
    assert json.loads((tmp_path / ".codex" / "hooks.json").read_text()) == json.loads(
        (ROOT / "compatibility" / "integrations" / "codex-v1.json").read_text()
    )
    assert (tmp_path / ".codex" / "config.toml").read_text() == (
        ROOT / "compatibility" / "integrations" / "codex-v1.toml"
    ).read_text()
    assert (tmp_path / ".config" / "opencode" / "plugins" / "codex-axi.js").read_text() == (
        ROOT / "compatibility" / "integrations" / "opencode-v1.js"
    ).read_text()
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


def test_setup_refuses_structurally_invalid_hook_config(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"hooks":[]}')
    with pytest.raises(AxiError) as caught:
        integrations.setup_hooks("claude", check=True)
    assert caught.value.code == "invalid_integration_config"
    assert path.read_text() == '{"hooks":[]}'


def test_setup_enables_existing_disabled_codex_feature(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(integrations, "_command", lambda: "codex-axi")
    path = tmp_path / ".codex" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text("[features]\nhooks = false\n")

    integrations.setup_hooks("codex")

    assert path.read_text() == "[features]\nhooks = true\n"


@pytest.mark.parametrize("unrelated", ["true", "false"])
def test_codex_setup_only_mutates_features_hooks(tmp_path, monkeypatch, unrelated):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(integrations, "_command", lambda: "codex-axi")
    path = tmp_path / ".codex" / "config.toml"
    path.parent.mkdir(parents=True)
    path.write_text(f"[other]\nhooks = {unrelated}\n\n[features]\nhooks = false\n")

    integrations.setup_hooks("codex")

    assert path.read_text() == f"[other]\nhooks = {unrelated}\n\n[features]\nhooks = true\n"


def test_hook_setup_preserves_unrelated_entry_that_mentions_codex_axi(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(integrations, "_command", lambda: "/new/codex-axi")
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    unrelated = {
        "matcher": "codex-axi project",
        "hooks": [{"type": "command", "command": "other-tool --label codex-axi"}],
    }
    path.write_text(json.dumps({"hooks": {"SessionStart": [unrelated]}}))

    integrations.setup_hooks("claude")
    entries = json.loads(path.read_text())["hooks"]["SessionStart"]
    assert unrelated in entries

    integrations.setup_hooks("claude", remove=True)
    assert json.loads(path.read_text())["hooks"]["SessionStart"] == [unrelated]


def test_check_and_remove_are_read_only_then_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(integrations, "_command", lambda: "codex-axi")
    integrations.setup_hooks("claude")
    path = tmp_path / ".claude" / "settings.json"
    before = path.read_text()
    checked = integrations.setup_hooks("claude", check=True)
    assert path.read_text() == before
    assert checked["setup"]["adapters"][0]["status"] == "current"
    removed = integrations.setup_hooks("claude", remove=True)
    assert removed["setup"]["changed"] == ["claude"]
    assert json.loads(path.read_text())["hooks"]["SessionStart"] == []


def test_codex_setup_refuses_malformed_toml(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text("[features\nhooks = true")
    with pytest.raises(AxiError) as caught:
        integrations.setup_hooks("codex")
    assert caught.value.code == "invalid_integration_config"
    assert config.read_text() == "[features\nhooks = true"


def test_opencode_remove_deletes_only_managed_plugin(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(integrations, "_command", lambda: "codex-axi")
    integrations.setup_hooks("opencode")
    unrelated = tmp_path / ".config" / "opencode" / "plugins" / "other.js"
    unrelated.write_text("export default {}")
    integrations.setup_hooks("opencode", remove=True)
    assert not (unrelated.parent / "codex-axi.js").exists()
    assert unrelated.exists()


def test_opencode_remove_refuses_drifted_plugin(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    path = tmp_path / ".config" / "opencode" / "plugins" / "codex-axi.js"
    path.parent.mkdir(parents=True)
    path.write_text("// user-owned replacement")
    with pytest.raises(AxiError) as caught:
        integrations.setup_hooks("opencode", remove=True)
    assert caught.value.code == "integration_drift"
    assert path.exists()
    with pytest.raises(AxiError):
        integrations.setup_hooks("opencode")


def test_opencode_remove_refuses_customization_after_managed_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(integrations, "_command", lambda: "codex-axi")
    integrations.setup_hooks("opencode")
    path = tmp_path / ".config" / "opencode" / "plugins" / "codex-axi.js"
    path.write_text(path.read_text() + "// user customization\n")
    with pytest.raises(AxiError) as caught:
        integrations.setup_hooks("opencode", remove=True)
    assert caught.value.code == "integration_drift"
    assert path.exists()


def test_all_targets_preflight_before_any_mutation(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text("[features")
    with pytest.raises(AxiError):
        integrations.setup_hooks("all")
    assert not (tmp_path / ".claude" / "settings.json").exists()


def test_command_preserves_absolute_path_with_spaces_when_not_on_path(tmp_path, monkeypatch):
    executable = tmp_path / "bin with spaces" / "codex-axi"
    monkeypatch.setattr(integrations.sys, "argv", [str(executable)])
    monkeypatch.setattr(integrations.shutil, "which", lambda _: None)
    assert integrations._command() == str(executable.resolve())
