"""Long-lived background worker process."""

from __future__ import annotations

import fcntl
import json
import sys
from pathlib import Path

from .app import CodexAxi
from .state import StateStore


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    payload = json.loads(Path(args[0]).read_text())
    app = CodexAxi(cwd=Path(payload["cwd"]), store=StateStore(Path(payload["state"])))
    lease_path = Path(payload["lease"])
    try:
        with lease_path.open("a+") as lease:
            fcntl.flock(lease, fcntl.LOCK_EX)
            app.start_worker(
                payload["message"],
                role=payload.get("role"),
                label=payload.get("label"),
                _rendezvous=Path(payload["rendezvous"]),
                _runner_lease=lease_path,
                **payload.get("options", {}),
            )
    finally:
        lease_path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
