"""Strict-decode representative TOON documents and verify semantic parity."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from codex_axi.output import toon


def decode(value: str) -> object:
    result = subprocess.run(
        ["npx", "-y", "@toon-format/cli", "--decode", "--strict", "-"],
        input=value,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def command_document(
    root: Path,
    arguments: list[str],
    *,
    json_output: bool,
    extra_env: dict[str, str] | None = None,
) -> tuple[int, object]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root / "src")
    env.update(extra_env or {})
    command = [sys.executable, "-m", "codex_axi.cli", *arguments]
    if json_output:
        command.append("--json")
    result = subprocess.run(command, text=True, capture_output=True, env=env, check=False)
    payload = json.loads(result.stdout) if json_output else decode(result.stdout)
    return result.returncode, payload


def fixture_environment(directory: Path, scenario: str) -> dict[str, str]:
    state = directory / "state.json"
    data: dict[str, object] = {"version": 1, "workers": {}, "tasks": {}, "active_turns": {}}
    if scenario in {"worker", "worker_list"}:
        data["workers"] = {
            "worker-fixture": {
                "kind": "worker",
                "status": "completed",
                "cwd": str(Path.cwd()) if scenario == "worker_list" else "/workspace",
                "role": "verifier",
                "final_response": "done",
            }
        }
    elif scenario == "events":
        journal = directory / "events.jsonl"
        journal.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "sequence": 1,
                    "method": "turn/completed",
                    "payload": {"turn": {"id": "turn-fixture"}},
                    "extension": False,
                },
                separators=(",", ":"),
            )
            + "\n"
        )
        data["workers"] = {
            "worker-fixture": {
                "kind": "worker",
                "status": "completed",
                "cwd": "/workspace",
                "event_log": str(journal),
                "event_turn_id": "turn-fixture",
            }
        }
    state.write_text(json.dumps(data))
    return {
        "CODEX_AXI_STATE": str(state),
        "HOME": str(directory),
        "USERPROFILE": str(directory),
        "PATH": "",
    }


def compare_command(root: Path, arguments: list[str], scenario: str = "empty") -> None:
    results = []
    for json_output in (False, True):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            env = fixture_environment(directory, scenario)
            results.append(
                command_document(root, arguments, json_output=json_output, extra_env=env)
            )
    if results[0] != results[1]:
        raise SystemExit(f"command output parity failed: {' '.join(arguments)}")


def main() -> int:
    root = Path(__file__).parents[1]
    documents = json.loads((root / "tests" / "fixtures" / "output" / "documents.json").read_text())
    for document in documents:
        encoded = toon(document)
        if decode(encoded) != document:
            raise SystemExit("TOON/JSON semantic parity check failed")
        if encoded.endswith("\n"):
            raise SystemExit("TOON output must not contain a trailing newline")
    commands = [
        (["--help"], "empty", None),
        (["task", "events", "--help"], "empty", None),
        (["task", "events", "thread", "--since", "-1"], "empty", "invalid_cursor"),
        ([], "empty", None),
        (["doctor"], "empty", None),
        (["worker", "list"], "empty", "worker_empty"),
        (["worker", "list"], "worker_list", "worker_list"),
        (["worker", "view", "worker-fixture"], "worker", "worker_detail"),
        (["worker", "events", "worker-fixture"], "events", "worker_events"),
        (["setup", "hooks", "--target", "all"], "empty", "setup_mutation"),
    ]
    goldens = json.loads(
        (root / "tests" / "fixtures" / "output" / "command-goldens.json").read_text()
    )
    for arguments, scenario, golden in commands:
        compare_command(root, arguments, scenario)
        if golden:
            with tempfile.TemporaryDirectory() as name:
                env = fixture_environment(Path(name), scenario)
                code, document = command_document(root, arguments, json_output=True, extra_env=env)
            if {"exit_code": code, "document": document} != goldens[golden]:
                raise SystemExit(f"command golden mismatch: {golden}")

    with tempfile.TemporaryDirectory() as name:
        directory = Path(name)
        env = fixture_environment(directory, "events")
        code, payload = command_document(
            root,
            ["worker", "events", "worker-fixture", "--follow"],
            json_output=True,
            extra_env=env,
        )
        if code != 0 or payload["schema_version"] != 1 or payload["sequence"] != 1:
            raise SystemExit("actual NDJSON event framing check failed")

    print(f"validated {len(documents)} output contracts and {len(commands)} CLI pairs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
