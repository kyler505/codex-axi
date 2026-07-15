# codex-axi

Codex control for agents — designed with [AXI](https://axi.md/) (Agent eXperience
Interface).

`codex-axi` gives another agent a compact, scriptable control surface for Codex
threads: dispatch work, retain a stable thread identity, observe progress,
steer an active turn, and resume it later. It uses token-efficient
[TOON](https://toonformat.dev/) on stdout, keeps diagnostics on stderr, and
returns structured, actionable errors.

It uses the official `openai-codex` Python SDK and the managed Codex
app-server runtime. It does not replace Codex's safety model, transport, or
thread store.

> **Alpha:** targets Codex `>=0.144.0,<0.145.0` and the beta
> `openai-codex` SDK. Run `codex-axi doctor` after installation.

## Quick start

Install the Agent Skill with [npx skills](https://www.npmjs.com/package/skills):

```sh
npx skills add kyler505/codex-axi --skill codex-axi -g
```

The skill teaches compatible agents when and how to use `codex-axi`. Install it
globally with `-g`, or omit `-g` to install it only for the current project.

You also need Python 3.10+, a supported authenticated `codex` CLI on `PATH`,
and macOS or Linux for the preferred managed-daemon path. Install the CLI with
`pipx`:

```sh
pipx install 'git+https://github.com/kyler505/codex-axi.git'
codex-axi doctor
```

With the CLI available, an agent can start immediately:

```sh
codex-axi                                      # current-workspace dashboard
codex-axi task start --message "Review this repository" --sandbox read-only
codex-axi worker start --background --message "Run the tests and fix one failure"
codex-axi worker list
```

## Other ways to use it

The skill is the recommended on-demand discovery path, but it is not required.

### Direct invocation

Any capable agent can call the CLI directly after installation. The no-argument
dashboard shows current-workspace state and next-step commands; each command
also has concise TOON `--help` output.

```sh
codex-axi task list
codex-axi task view <thread>
codex-axi worker follow <thread> --timeout 60
```

### Session hooks

Want a compact workspace dashboard injected at the start of every session?
Install the CLI globally, then opt into a hook for Claude Code, Codex,
OpenCode, or all three:

```sh
codex-axi setup hooks --target all
```

Setup preserves unrelated configuration, repairs a moved executable path, and
is a no-op when it is already current. Restart the target agent session after
installation. Hooks provide live ambient state; the skill provides on-demand
guidance. Either may be used alone.

## Usage

```sh
# Foreground Codex task: waits for the final result.
codex-axi task start --message "Review the parser" --sandbox read-only

# Persistent worker: returns after dispatch so the caller can control it later.
codex-axi worker start --background --role verifier \
  --message "Run the test suite and report one actionable failure"
codex-axi worker follow <thread> --timeout 60
codex-axi worker send <thread> --message "Now inspect only the parser tests"
codex-axi worker interrupt <thread>
codex-axi worker close <thread>

# Resume, steer, or archive a normal task.
codex-axi task steer <thread> --message "Focus only on lifecycle cleanup"
codex-axi task resume <thread> --message "Continue with the narrowed scope"
codex-axi task archive <thread>

# Inspect a real Codex parent-child relationship or request native delegation.
codex-axi delegate --message "Delegate repository inspection when useful" --sandbox read-only
codex-axi agent list <root-thread>

# Check the Codex runtime selected by the CLI.
codex-axi doctor
codex-axi daemon status
```

Use `--sandbox read-only` for inspection-only work. The default is
`workspace-write`; `full-access` is never selected implicitly. Approval defaults
to `auto-review`; use `--approval deny-all` when the caller must not encounter a
new approval request.

### Command groups

| Command | What it does |
| --- | --- |
| `codex-axi` | Show a compact dashboard for the current workspace. |
| `task` | Start, list, view, follow, steer, interrupt, resume, or archive Codex threads. |
| `worker` | Start and control deterministic AXI-managed threads. |
| `agent` | Inspect native Codex subagents attached to a root thread. |
| `delegate` | Ask a root Codex task to delegate work natively. |
| `doctor`, `daemon status` | Probe runtime and managed-daemon compatibility. |
| `setup hooks` | Install opt-in Claude Code, Codex, or OpenCode session hooks. |
| `mcp-server` | Run the optional thin MCP adapter. |

Use `codex-axi <command> --help` for supported flags, defaults, and examples.
Unknown flags fail before a runtime call with exit status `2`; command errors
remain structured on stdout so agents can recover without parsing dependency
output.

## Workers are not native subagents

A **worker** is an ordinary Codex thread created and tracked by `codex-axi` so
an external caller can deterministically list, follow, steer, interrupt, and
close it. The caller owns decomposition and aggregation.

A native **subagent** is a child spawned and managed by a parent Codex agent.
Only Codex creates that parent-child relationship. `codex-axi agent` reports it
when Codex supplies it; independent workers are never presented as native
subagents.

## How it works

```text
agent harness
    -> codex-axi CLI / optional thin MCP adapter
    -> official openai-codex Python SDK
    -> managed Codex app-server proxy and daemon, or SDK direct fallback
    -> Codex app-server
```

The CLI is the source of truth. Codex remains authoritative for persisted
threads and turns; `codex-axi` records only the worker metadata and active-turn
coordination needed for deterministic control. Read the
[architecture overview](docs/ARCHITECTURE.md) for the boundary and lifecycle,
and [runtime compatibility notes](docs/IMPLEMENTATION.md) for version-specific
behavior.

## Optional MCP adapter

The CLI is the primary interface. If an MCP host needs it, install the optional
adapter; it exposes the same application behavior rather than a second
orchestration model.

```sh
pipx install 'codex-axi[mcp] @ git+https://github.com/kyler505/codex-axi.git'
codex-axi mcp-server
```

## Evaluation and development

[Benchmark notes](docs/BENCHMARKS.md) separate a local dispatch probe from the
repeatable lifecycle, recovery, native-delegation, ambient-context, safety, and
structured-output checks. The single probe is directional evidence only, not a
general performance claim.

For a source checkout:

```sh
git clone https://github.com/kyler505/codex-axi.git
cd codex-axi
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,mcp]'
.venv/bin/python -m pytest
.venv/bin/ruff check src tests
PYTHONPATH=src .venv/bin/python -m codex_axi.skill --check
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidance and
[SECURITY.md](SECURITY.md) for private vulnerability reporting. MIT licensed.
