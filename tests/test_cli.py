from codex_axi.cli import build_parser, main
from codex_axi.runtime import RuntimeCapabilities


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


def test_doctor_fails_when_codex_is_not_authenticated(monkeypatch, capsys):
    monkeypatch.setattr(
        "codex_axi.cli.probe_runtime",
        lambda: RuntimeCapabilities(
            "/bin/codex", "codex-cli 0.144.3", True, True, "healthy", authenticated=False
        ),
    )
    assert main(["doctor"]) == 1
    output = capsys.readouterr().out
    assert "authenticated: false" in output
    assert "status: unauthenticated" in output


def test_foreground_commands_accept_timeout():
    parser = build_parser()
    start = parser.parse_args(["task", "start", "--message", "x", "--timeout", "12"])
    resume = parser.parse_args(
        ["task", "resume", "thread", "--message", "x", "--timeout", "12"]
    )
    steer = parser.parse_args(
        ["task", "steer", "thread", "--message", "x", "--timeout", "2"]
    )
    assert start.timeout == 12
    assert resume.timeout == 12
    assert steer.timeout == 2
