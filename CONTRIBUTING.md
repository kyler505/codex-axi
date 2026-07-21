# Contributing

Thanks for helping improve codex-axi. The project is alpha software and its
app-server compatibility boundary is intentionally narrow.

## Development setup

```sh
git clone https://github.com/kyler505/codex-axi.git
cd codex-axi
uv sync --locked --all-extras
```

Before changing architecture or command semantics, read
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Preserve the distinction between
AXI-managed workers and native Codex subagents.

## Checks

```sh
uv run python -m pytest
uv run ruff check src tests
uv run python -m codex_axi.skill --check
uv run python -m build
uv run twine check dist/*
uv run python scripts/check_output_contracts.py
```

Add focused tests with behavior changes. Keep stdout TOON-only and send
diagnostic or progress output to stderr. Do not include credentials, local
Codex state, transcripts, or generated worker logs in commits or bug reports.

Open an issue before a broad architecture change. Small fixes can go directly
to a pull request with a concise problem statement and verification notes.

If capability tests disagree with the lockfile, run `uv sync --locked --all-extras`
and `uv run python -m pytest tests/test_runtime.py`. Production `doctor` always
reports the SDK installed in the environment where it runs.
