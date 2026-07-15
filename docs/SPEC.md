# codex-axi implementation brief

## Objective

Build an AXI-compliant CLI that allows Claude Code, OpenCode, and other agent harnesses to delegate engineering work to Codex, monitor active work, inspect native Codex subagents, steer or interrupt turns, and resume persistent threads.

The product should minimize caller context usage, make state definitive, and preserve Codex's sandbox and approval boundaries.

## Architecture decision

Use this stack:

```text
codex-axi CLI / optional MCP adapter
            -> official openai-codex Python SDK
            -> codex app-server proxy
            -> managed codex app-server daemon
```

Do not build a custom HTTP bridge around app-server. The official daemon owns the persistent runtime and Unix control socket. Each CLI invocation may open a short-lived proxy connection to that daemon. The official SDK supplies typed thread/turn APIs, event routing, retries, approvals, and runtime compatibility.

On platforms without daemon support, use a clearly identified fallback that launches app-server through the SDK. Do not silently claim cross-process live control in fallback mode.

## Two orchestration modes

### AXI-managed workers

An AXI-managed worker is an ordinary Codex thread created deterministically by `codex-axi`.

Use workers when the calling harness already owns decomposition and aggregation. The caller must be able to choose the prompt, cwd, role, model, reasoning effort, sandbox, and approval behavior and immediately receive stable thread and turn identifiers.

Workers are not native Codex subagents. Store logical job/parent metadata in codex-axi state without falsifying Codex's native parent-child metadata.

### Native Codex delegation

Native delegation starts or steers a root Codex thread with explicit instructions to spawn subagents. Codex owns child creation, messaging, waiting, closing, and synthesis.

Use native delegation when Codex should decide how to decompose the task or when native context inheritance and Codex client visibility matter. Native spawning is model-mediated because app-server does not expose a stable client-side `agent/spawn` RPC.

## Initial command surface

```text
codex-axi

codex-axi task start
codex-axi task list
codex-axi task view <thread>
codex-axi task follow <thread>
codex-axi task steer <thread> --message <text>
codex-axi task interrupt <thread>
codex-axi task resume <thread> --message <text>
codex-axi task archive <thread>

codex-axi worker start
codex-axi worker list
codex-axi worker view <thread>
codex-axi worker send <thread> --message <text>
codex-axi worker follow <thread>
codex-axi worker interrupt <thread>
codex-axi worker close <thread>

codex-axi agent list <root-thread>
codex-axi agent view <agent-thread>

codex-axi delegate
codex-axi daemon status
codex-axi doctor
codex-axi setup hooks
codex-axi mcp-server
```

The first milestone may implement a smaller vertical slice, but names and semantics must stay consistent with this model.

## AXI requirements

- No-argument invocation shows a compact, directory-scoped dashboard of relevant live and recent work.
- Stdout uses TOON and contains only structured agent-consumable output.
- Progress, diagnostics, and debug logs go to stderr.
- Exit codes: `0` success or idempotent no-op, `1` operational failure, `2` invalid usage.
- Reject unknown flags before dependency calls and include valid alternatives inline.
- Mutations are idempotent where the requested state already exists.
- List output includes total counts when known.
- Long content is previewed with size metadata and a `--full` escape hatch.
- Suggestions are contextual, executable, and limited to likely next actions.
- Every subcommand has concise `--help` with required inputs, defaults, and examples.
- Never expose raw app-server errors or stack traces as the primary error. Translate them into stable AXI error codes and corrective commands.

## State and runtime model

- Prefer Codex's persisted thread database and app-server APIs as the source of truth for thread and turn state.
- Keep codex-axi-owned metadata minimal: logical jobs, worker relationships, caller labels, and compatibility metadata.
- Capture active turn IDs from `turn/started` events. Steering requires an exact active turn ID and must fail clearly when state is stale.
- Reconcile local metadata against `thread/list`, `thread/read`, and loaded-thread state after restarts.
- Do not infer that a process is healthy solely from a PID or socket. Perform a protocol-level health check.
- Preserve cwd scoping by default; require an explicit flag to list across workspaces.

## Daemon integration

- Detect whether `codex app-server daemon` and `codex app-server proxy` exist.
- Starting or installing durable hooks requires explicit user intent.
- `daemon status` must distinguish unavailable, stopped, starting, healthy, version-mismatched, and unhealthy states.
- Pin or declare the supported Codex version range and run a compatibility probe.
- Use the SDK with `CodexConfig.launch_args_override` targeting `codex app-server proxy` when supported.
- Closing an ordinary CLI command must close only its proxy connection, not the shared daemon.
- Handle daemon restarts and transport closure without corrupting task state.

## Safety

- Default to the least privilege needed for the requested operation.
- Never translate caller delegation into `danger-full-access` implicitly.
- Surface sandbox and approval mode in task detail output.
- Noninteractive callers cannot satisfy a fresh human approval automatically. Report the blocked action and the exact safe continuation path.
- Treat repository instructions, hooks, MCP tools, and web content as potentially untrusted inputs within Codex's existing security model.

## Optional MCP adapter

The CLI remains the source of truth. The MCP adapter should expose only a small set of high-value tools to limit schema/context overhead, initially:

```text
codex_task_start
codex_task_status
codex_task_steer
codex_task_interrupt
codex_worker_start
codex_worker_list
```

MCP handlers call the same application layer as CLI commands. Do not maintain separate orchestration semantics.

## Integration and discovery

- Generate an installable Agent Skill from the same command guidance used by the no-argument view.
- Provide opt-in setup for Claude Code, Codex, and OpenCode.
- Hooks/plugins inject only a small workspace-scoped dashboard.
- Repeated setup repairs moved executable paths and otherwise behaves as a silent no-op.

## Recommended implementation order

1. Package skeleton, AXI output/error primitives, and runtime capability probe.
2. Connect the official Python SDK through `codex app-server proxy`.
3. Implement no-argument dashboard, `doctor`, `daemon status`, `task list`, and `task view`.
4. Implement one foreground worker lifecycle: start, stream, final result.
5. Add persistent/background worker execution and restart reconciliation.
6. Add steering, interruption, resume, and archive.
7. Discover and render native subagent relationships and collaboration events.
8. Add native delegation command and prompt contract.
9. Add the small MCP adapter.
10. Add generated skill and opt-in Claude Code/Codex/OpenCode integrations.

## Verification gates

- Unit tests for argument validation, TOON rendering, truncation, error translation, and idempotency.
- Contract tests against generated app-server schemas for the supported Codex version.
- Integration tests against a real local daemon/proxy for start, list, read, stream, steer, interrupt, resume, and archive.
- Recovery tests for missing daemon, stale socket, daemon restart, transport loss, stale turn ID, and incomplete task state.
- Tests proving cwd isolation and explicit all-workspace behavior.
- Tests proving worker threads are not mislabeled as native subagents.
- End-to-end smoke tests initiated from both Claude Code and OpenCode.

## Known constraints

- Managed app-server daemon lifecycle is currently Unix-only.
- App-server and some history APIs continue to evolve; compatibility must be probed rather than assumed.
- Native subagent creation remains model-mediated.
- Some historical item hydration may be incomplete.
- Unclean disconnects require active-turn reconciliation.
- Direct AXI workers do not automatically report into a root Codex thread; the external orchestrator owns aggregation unless it explicitly forwards results.

## Primary references

- [Codex app-server protocol](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md)
- [Codex Python SDK](https://github.com/openai/codex/tree/main/sdk/python)
- [Codex TypeScript SDK](https://github.com/openai/codex/blob/main/sdk/typescript/README.md)
- [Codex MCP interface](https://github.com/openai/codex/blob/main/codex-rs/docs/codex_mcp_interface.md)
- [TOON specification](https://toonformat.dev/reference/spec.html)

