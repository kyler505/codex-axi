# Architecture

codex-axi is a compact command-line control surface for delegating work to
Codex from another agent harness. The CLI is the source of truth; optional
integrations expose the same application behavior without creating a second
orchestration model.

## Runtime path

```text
agent harness
    -> codex-axi CLI / thin optional MCP adapter
    -> official openai-codex Python SDK
    -> managed app-server proxy and daemon, or identified SDK fallback
    -> Codex app-server
```

The official SDK owns typed thread and turn operations, event routing,
approvals, and transport behavior. codex-axi does not implement a custom
app-server protocol client or daemon manager.

When the managed daemon and proxy complete a protocol-level health check,
short-lived CLI invocations connect through that shared runtime. If the
installed platform or Codex version cannot support that path, codex-axi reports
the limitation and uses the SDK's direct app-server fallback only where doing
so does not imply cross-process live control.

## Tasks, workers, and native subagents

A **task** is a Codex thread operated through the general task command group.

A **worker** is an ordinary Codex thread created and tracked by codex-axi for a
caller that owns decomposition and result aggregation. codex-axi stores only
the metadata it needs for deterministic control, such as a label, role,
workspace, active turn identity, and requested safety modes.

A native **subagent** is a child created and managed by a parent Codex agent.
Native delegation is model-mediated, and codex-axi only reports a child as a
subagent when Codex supplies the real parent-child relationship. Workers are
never represented as native subagents.

## State and control

Codex's persisted thread data remains authoritative for threads and turns.
codex-axi keeps minimal local metadata for worker relationships and active-turn
coordination, then reconciles it against the runtime after interruptions or
restarts.

Steering and interruption require an exact active turn identifier. A stale or
missing identifier fails explicitly instead of guessing which turn to control.
Closing a normal CLI invocation closes only its SDK connection, not the shared
daemon.

## Agent-facing output

Stdout contains structured TOON data only. Diagnostics and progress belong on
stderr. Successful no-ops exit with status `0`, operational failures with `1`,
and invalid usage with `2`. Unknown flags are rejected before a runtime call,
long content is previewed with a full-content escape hatch, and list results
remain workspace-scoped unless the caller explicitly requests all workspaces.

The no-argument command presents a compact workspace dashboard. The generated
Agent Skill and opt-in Claude Code, Codex, and OpenCode integrations derive from
the same command guidance so discovery surfaces do not drift.

## Safety boundary

codex-axi preserves Codex sandbox and approval behavior. It never selects
full-access implicitly, and it cannot satisfy a new human approval on behalf of
a noninteractive caller. Repository instructions, hooks, prompts, MCP tools,
and web content remain untrusted inputs within Codex's existing security model.

Runtime-specific compatibility details are documented in
[`IMPLEMENTATION.md`](IMPLEMENTATION.md).
