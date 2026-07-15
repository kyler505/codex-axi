# codex-axi

An agent-native CLI for delegating engineering work to Codex, observing active
work, steering turns, and resuming persistent threads through a compact Agent
eXperience Interface (AXI).

> **Alpha:** codex-axi currently targets Codex `>=0.144.0,<0.145.0` and the
> beta `openai-codex` Python SDK. Run `codex-axi doctor` after installation.

## Why codex-axi?

Agent harnesses can use codex-axi without absorbing a large tool schema or
reimplementing Codex orchestration. Stdout is structured, token-efficient TOON;
diagnostics stay on stderr; usage errors are self-correcting; and workspace
scoping is the default.

codex-axi exposes two deliberately different concepts:

- A **worker** is an ordinary Codex thread created and tracked by codex-axi for
  deterministic external orchestration.
- A native **subagent** is a child spawned and managed by a parent Codex agent.

Workers are never labeled as native subagents.

## Dispatch benchmark

In a local single-run probe on 2026-07-15, Claude Code was asked to launch
the same harmless, read-only Codex prompt through each path. The prompt only
returned `BENCHMARK_OK`; it did not use tools or change the repository.

| Path | Claude dispatch-return time | Result | Control surface after dispatch |
| --- | ---: | --- | --- |
| Vanilla Claude Code → `codex exec --ephemeral` | 25.57s | Completed inline with `BENCHMARK_OK` | None: the caller waited for a one-shot process |
| Claude Code → `codex-axi worker start --background` | 12.38s | Returned a running worker; it later completed with `BENCHMARK_OK` | Worker ID, follow, steer, interrupt, and close |

The AXI path returned control to Claude Code **51.6% sooner** in this probe.
This is directional evidence, not a general latency claim: it is one run on a
specific machine and the two paths intentionally have different completion
semantics. Vanilla `codex exec` blocks until completion; an AXI background
worker acknowledges dispatch and lets the caller observe or control the work
later. Neither row represents a native Codex subagent. Use `codex-axi agent`
and `codex-axi delegate` when working with real parent-owned native subagents.

See [`docs/BENCHMARKS.md`](docs/BENCHMARKS.md) for the repeatable latency
protocol and lifecycle, recovery, native-delegation, ambient-context, safety,
and structured-output demonstrations.

## Requirements

- Python 3.10 or newer
- A supported `codex` CLI on `PATH`, authenticated for normal Codex use
- macOS or Linux for the managed app-server daemon path

The daemon is preferred when its protocol handshake succeeds. With Codex
0.144.x, codex-axi transparently uses the official SDK's direct app-server
fallback for non-shared operations when the managed proxy is incompatible. See
[`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md) for the exact limitation.

## Install

Install the CLI from GitHub with an isolated Python environment:

```sh
pipx install 'git+https://github.com/kyler505/codex-axi.git'
codex-axi doctor
```

For the optional MCP server:

```sh
pipx install 'codex-axi[mcp] @ git+https://github.com/kyler505/codex-axi.git'
```

To work from a clone:

```sh
git clone https://github.com/kyler505/codex-axi.git
cd codex-axi
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,mcp]'
.venv/bin/codex-axi doctor
```

## Quick start

Running without arguments shows recent work scoped to the current directory:

```sh
codex-axi
```

Start a foreground task or a persistent background worker:

```sh
codex-axi task start --message "Review this repository for correctness"
codex-axi worker start --background --message "Run the test suite and fix one failure"
codex-axi worker list
codex-axi worker follow <thread>
```

Steer or interrupt an active turn using its exact recorded turn identity:

```sh
codex-axi task steer <thread> --message "Focus only on the parser"
codex-axi task interrupt <thread>
codex-axi task resume <thread> --message "Continue with the narrowed scope"
```

Use `--sandbox read-only` for inspection-only work. The default is
`workspace-write`; `full-access` is never selected implicitly. Approval defaults
to `auto-review`, and `--approval deny-all` is available for callers that must
not encounter a fresh approval request.

## Command groups

```text
codex-axi                         Workspace dashboard
codex-axi doctor                  Runtime and compatibility probe
codex-axi daemon status           Managed daemon status
codex-axi task ...                Start, list, view, steer, interrupt, resume, archive
codex-axi worker ...              Start, list, view, send, follow, interrupt, close
codex-axi agent ...               Inspect real native Codex subagents
codex-axi delegate ...            Ask a root Codex task to delegate natively
codex-axi setup hooks ...         Opt-in ambient integrations
codex-axi mcp-server              Optional thin MCP adapter
```

Every command has structured `--help`, including inputs, defaults, and examples.

## Agent integrations

Ambient workspace context is opt-in:

```sh
codex-axi setup hooks --target codex
codex-axi setup hooks --target claude
codex-axi setup hooks --target opencode
codex-axi setup hooks --target all
```

Setup preserves unrelated configuration, repairs a moved executable path, and
is a no-op when already current. Review configuration changes before enabling
hooks in a sensitive environment.

An installable Agent Skill is also generated at
[`skills/codex-axi/SKILL.md`](skills/codex-axi/SKILL.md). The hook provides live
ambient state; the skill provides on-demand discovery. Either can be used alone.

## Architecture

```text
agent harness
    -> codex-axi CLI (source of truth) / thin optional MCP adapter
    -> official openai-codex Python SDK
    -> managed proxy and daemon, or identified SDK fallback
    -> Codex app-server
```

codex-axi does not implement a custom app-server transport or process manager.
Its local metadata contains only worker relationships, labels, compatibility
data, and active-turn coordination. Codex's persisted thread database remains
the source of truth for threads and turns.

The public design overview is [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
Current runtime compatibility notes are in
[`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md).

## Development

```sh
.venv/bin/python -m pytest
.venv/bin/ruff check src tests
PYTHONPATH=src .venv/bin/python -m codex_axi.skill --check
.venv/bin/python -m build
.venv/bin/python -m twine check dist/*
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for contribution guidance and
[`SECURITY.md`](SECURITY.md) for private vulnerability reporting. This project
is available under the [MIT License](LICENSE).
