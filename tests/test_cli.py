import json

import pytest

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


def test_json_output_applies_to_help_and_errors(capsys):
    assert main(["task", "start", "--help", "--json"]) == 0
    help_document = json.loads(capsys.readouterr().out)
    assert help_document["command"] == "codex-axi task start"

    assert main(["task", "start", "--message", "x", "--bad", "--json"]) == 2
    error_document = json.loads(capsys.readouterr().out)
    assert error_document["code"] == "invalid_usage"


def test_json_text_remains_a_message_value():
    args = build_parser().parse_args(["task", "start", "--message=--json"])
    assert args.message == "--json"


def test_invalid_output_environment_is_usage_error(monkeypatch, capsys):
    monkeypatch.setenv("CODEX_AXI_OUTPUT", "xml")
    assert main(["task", "list"]) == 2
    output = capsys.readouterr().out
    assert "Unsupported CODEX_AXI_OUTPUT value: xml" in output
    assert "code: invalid_usage" in output


@pytest.mark.parametrize(
    "arguments, message",
    [
        (["task", "list", "--limit", "0"], "limit must be one or greater"),
        (["task", "list", "--limit", "-1"], "limit must be one or greater"),
        (
            ["task", "start", "--message", "x", "--cwd", "/definitely/not/a/codex-axi-dir"],
            "cwd does not exist",
        ),
    ],
)
def test_invalid_limits_and_cwd_fail_before_runtime(arguments, message, monkeypatch, capsys):
    monkeypatch.setattr(
        "codex_axi.cli.probe_runtime", lambda: pytest.fail("runtime must not be probed")
    )
    assert main(arguments) == 2
    assert message in capsys.readouterr().out


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
    resume = parser.parse_args(["task", "resume", "thread", "--message", "x", "--timeout", "12"])
    steer = parser.parse_args(["task", "steer", "thread", "--message", "x", "--timeout", "2"])
    assert start.timeout == 12
    assert resume.timeout == 12
    assert steer.timeout == 2


def test_doctor_full_controls_capability_detail():
    parser = build_parser()
    assert parser.parse_args(["doctor"]).full is False
    assert parser.parse_args(["doctor", "--full"]).full is True


def test_event_capture_and_follow_flags():
    parser = build_parser()
    start = parser.parse_args(["worker", "start", "--message", "x", "--events"])
    events = parser.parse_args(
        ["worker", "events", "thread", "--follow", "--since", "4", "--limit", "20"]
    )
    assert start.events is True
    assert events.follow is True
    assert events.since == 4
    assert events.limit == 20


def test_event_follow_requires_json_before_runtime(monkeypatch, capsys):
    monkeypatch.setattr(
        "codex_axi.cli.probe_runtime", lambda: pytest.fail("runtime must not be probed")
    )
    assert main(["task", "events", "thread", "--follow"]) == 2
    assert "--follow` requires `--json" in capsys.readouterr().out


def test_event_cursor_rejects_negative_values():
    assert main(["task", "events", "thread", "--since", "-1"]) == 2
