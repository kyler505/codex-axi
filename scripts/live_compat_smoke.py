"""Opt-in live compatibility smoke; requires an authenticated local Codex install."""

from __future__ import annotations

import json
import subprocess
import sys


def run(*args: str) -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "codex_axi.cli", *args, "--json"],
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode:
        raise SystemExit(result.stdout or result.stderr)
    return json.loads(result.stdout)


def main() -> int:
    doctor = run("doctor")
    if doctor["status"] == "unauthenticated":
        raise SystemExit("codex-axi live smoke requires `codex login`")
    task = run(
        "task",
        "start",
        "--message",
        "Reply with COMPATIBILITY_OK",
        "--sandbox",
        "read-only",
        "--approval",
        "deny-all",
        "--timeout",
        "120",
        "--events",
    )
    if "COMPATIBILITY_OK" not in task["task"]["final_response"]:
        raise SystemExit("live task did not return the expected marker")
    events = run("task", "events", task["task"]["id"])
    if not events["events"]:
        raise SystemExit("live task produced no captured events")
    worker = run(
        "worker",
        "start",
        "--background",
        "--message",
        "Run a 30 second wait command, then reply WAIT_DONE",
        "--sandbox",
        "read-only",
        "--approval",
        "deny-all",
        "--events",
    )
    interrupted = run("worker", "interrupt", worker["worker"]["id"])
    if interrupted["worker"]["status"] != "interrupted":
        raise SystemExit("background worker interruption was not acknowledged")
    print(
        json.dumps(
            {"status": "passed", "thread": task["task"]["id"], "worker": worker["worker"]["id"]}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
