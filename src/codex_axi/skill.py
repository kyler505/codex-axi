from __future__ import annotations

import argparse
from pathlib import Path

from .guidance import render_skill


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = Path(__file__).parents[2] / "skills" / "codex-axi" / "SKILL.md"
    expected = render_skill()
    if args.check:
        return 0 if path.read_text() == expected else 1
    path.write_text(expected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
