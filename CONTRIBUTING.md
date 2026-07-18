# Contributing

Thanks for helping improve codex-axi. The project is alpha software and its
app-server compatibility boundary is intentionally narrow.

## Development setup

```sh
git clone https://github.com/kyler505/codex-axi.git
cd codex-axi
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,mcp]'
```

Before changing architecture or command semantics, read
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Preserve the distinction between
AXI-managed workers and native Codex subagents.

## Checks

```sh
.venv/bin/python -m pytest
.venv/bin/ruff check src tests
.venv/bin/python -m codex_axi.skill --check
.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
.venv/bin/python scripts/check_output_contracts.py
```

Add focused tests with behavior changes. Keep stdout TOON-only and send
diagnostic or progress output to stderr. Do not include credentials, local
Codex state, transcripts, or generated worker logs in commits or bug reports.

Open an issue before a broad architecture change. Small fixes can go directly
to a pull request with a concise problem statement and verification notes.
