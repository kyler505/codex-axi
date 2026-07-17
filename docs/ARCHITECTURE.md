# Architecture

`codex-axi` is an AXI command-line control surface for an agent that needs to
dispatch and control Codex work through shell execution. Its job is to make
Codex state discoverable and controllable without inventing another runtime.

## System boundary

```text
agent harness
    -> codex-axi CLI / optional thin MCP adapter
    -> official openai-codex Python SDK
    -> managed app-server proxy and daemon, or SDK direct fallback
    -> Codex app-server
```

The CLI is the source of truth for this interface. The official SDK owns typed
thread and turn operations, event routing, approval handling, and transport.
`codex-axi` does not implement an app-server protocol client, daemon manager,
or competing orchestration layer. The optional MCP adapter is deliberately thin
and reuses the CLI application behavior.

## What persists where

| Concern | Authority |
| --- | --- |
| Codex thread and turn history | Codex persisted thread data |
| Thread and turn operations | Official `openai-codex` SDK |
| Worker relationship, label, workspace, safety options, active-turn identity | Minimal local `codex-axi` metadata |
| Agent-facing command contract | `codex-axi` CLI |

Local metadata is reconciled with the Codex runtime after interruption or
restart. It is coordination state, not a shadow copy of Codex history.

## Tasks, workers, and native subagents

| Concept | Owner | Purpose |
| --- | --- | --- |
| **Task** | Caller / Codex | A regular Codex thread operated with `task`. |
| **Worker** | External caller through `codex-axi` | A regular Codex thread with metadata that enables deterministic external control. |
| **Native subagent** | Parent Codex agent | A real child relationship created and managed by Codex itself. |

Workers are never native Codex subagents. A caller uses workers when it owns
decomposition and aggregation; a caller uses `delegate` when it wants a root
Codex task to decide whether to create native children. `agent list` exposes
only relationships Codex actually reports.

## Runtime selection

The managed daemon is probed through Codex's protocol-level health check. A
healthy daemon is used as a shared runtime only when the installed SDK also
supports its control transport. Otherwise, the CLI reports the transport
limitation separately and uses the SDK's direct app-server fallback for
operations that do not claim daemon-backed control. Closing a CLI invocation
closes its SDK connection, not the shared daemon.

The precise version-specific behavior belongs in
[Implementation notes](IMPLEMENTATION.md), not in the command contract.

## Active-turn control

Steering and interruption require the exact active turn ID recorded at dispatch.
On restart or interruption, the CLI reconciles stored metadata with runtime
state before it offers more control. A stale or missing ID fails explicitly;
the CLI never guesses which turn to steer or interrupt.

```text
start/resume
  -> record worker/task metadata and exact active turn ID
  -> run or acknowledge work
  -> reconcile terminal state and clear active turn ID
```

## Agent-facing contract

The command line follows AXI conventions:

- stdout is structured, token-efficient TOON by default: data, errors, and
  actionable help. Callers can explicitly select JSON without changing schemas.
- stderr is for diagnostics and progress only.
- exit `0` means success, including an idempotent no-op; `1` is an operational
  error; `2` is invalid usage.
- no arguments show a compact, workspace-scoped dashboard rather than a usage
  wall; `--help` is concise and command-specific.
- lists are workspace-scoped by default, long content is previewed with a
  `--full` escape hatch, and unknown flags fail before any runtime call.

The installable Agent Skill and opt-in Claude Code, Codex, and OpenCode hooks
derive from the same command guidance, preventing discovery surfaces from
drifting.

## Safety boundary

`codex-axi` passes Codex sandbox and approval choices through; it does not
implicitly select full access or satisfy a new human approval for a
noninteractive caller. Repository instructions, hooks, prompts, MCP tools, and
web content remain untrusted inputs within Codex's existing security model.
