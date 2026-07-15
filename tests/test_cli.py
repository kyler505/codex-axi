from codex_axi.cli import main


def test_unknown_flag_is_usage_error(capsys):
    assert main(["task", "start", "--message", "x", "--unknown"]) == 2
    output = capsys.readouterr().out
    assert "unknown flag or argument --unknown" in output
    assert "--sandbox" in output
    assert "code: invalid_usage" in output
    assert not output.endswith("\n")


def test_help_is_structured_toon(capsys):
    assert main(["task", "start", "--help"]) == 0
    output = capsys.readouterr().out
    assert 'command: "codex-axi task start"' in output
    assert "examples[2]:" in output
    assert "default" in output
    assert not output.endswith("\n")
