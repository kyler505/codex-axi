# Evaluation: dispatch and lifecycle control

`codex-axi` is useful when a caller needs to dispatch Codex work and retain a
deterministic control surface afterward. These checks separate a one-shot local
dispatch probe from repeatable demonstrations of lifecycle control. They are
not a general performance benchmark and should not be read as a claim about
Codex model latency.

## Terminology

- **Vanilla path:** an agent harness invokes `codex exec`; the process owns the
  run and normally blocks until it finishes.
- **AXI worker:** an ordinary Codex thread started and tracked by `codex-axi`.
  A worker is not a native Codex subagent.
- **Native subagent:** a child owned by a parent Codex agent. Only Codex can
  create this relationship; inspect it with `codex-axi agent list`.

## Measured dispatch probe

This single-run local probe was performed on 2026-07-15 using Claude Code
2.1.210, Codex CLI 0.144.3, and the same harmless read-only prompt:
`Reply with exactly BENCHMARK_OK and do not use tools.`

| Path | Claude dispatch-return time | Work result | State retained after dispatch |
| --- | ---: | --- | --- |
| `codex exec --sandbox read-only --ephemeral` | 25.57s | `BENCHMARK_OK` | None; the caller waited for the process |
| `codex-axi worker start --background --sandbox read-only --approval deny-all` | 12.38s | `BENCHMARK_OK` | Worker and turn IDs; status, follow, steer, interrupt, and close |

The AXI invocation returned control 51.6% sooner in this run. Treat that as
directional: it is a single machine/run comparison, and the commands have
intentionally different completion semantics. The meaningful product
difference is that the AXI worker can be controlled after launch.

## Repeatable latency benchmark

Run each command ten times from the same repository and record elapsed wall
time, Claude session cost, Codex version, model, sandbox, approval mode, and
daemon state. Do not combine cold and warm runs in one summary: report them
as separate cohorts.

```sh
# Baseline: synchronous one-shot Codex process
claude -p --safe-mode --permission-mode bypassPermissions --allowedTools Bash \
  --output-format json \
  'Use exactly one Bash command: codex exec --sandbox read-only --ephemeral "Reply with exactly BENCHMARK_OK and do not use tools." Then reply DONE.'

# AXI: acknowledge a persistent worker, then observe it separately
claude -p --safe-mode --permission-mode bypassPermissions --allowedTools Bash \
  --output-format json \
  'Use exactly one Bash command: codex-axi worker start --background --sandbox read-only --approval deny-all --label benchmark --message "Reply with exactly BENCHMARK_OK and do not use tools." Then reply DONE.'
```

Report median and p95 for:

| Metric | Definition |
| --- | --- |
| Dispatch return | Start of the caller command to its completion |
| Worker completion | Successful dispatch acknowledgement to terminal worker state |
| End-to-end completion | Start of the caller command to terminal Codex result |
| Control acknowledgement | `steer` or `interrupt` request to terminal acknowledgement |
| Failure rate | Nonzero exits, missing IDs, or unexpected terminal state / total runs |

## Lifecycle-control demonstration

Use a deliberately slow, read-only task so there is time to issue controls.
The demonstration passes only when every action addresses the same worker and
the exact active turn recorded at dispatch.

```sh
codex-axi worker start --background --label lifecycle-demo \
  --sandbox read-only --approval deny-all \
  --message "Inspect the repository slowly. Do not edit files; report findings after each major area."

codex-axi worker follow <worker-id> --timeout 2
codex-axi worker send <worker-id> --message "Now inspect only src/codex_axi/runtime.py."
codex-axi worker interrupt <worker-id>
codex-axi worker view <worker-id>
```

Expected evidence:

| Capability | AXI evidence | One-shot `codex exec` equivalent |
| --- | --- | --- |
| Persistent identity | Worker ID and active turn ID | No independent controller identity after caller exit |
| Observation | `worker follow` / `worker view` | Keep the original process attached and parse its output |
| Mid-turn steering | `worker send` targets the exact active turn | No stable post-launch control surface |
| Interruption | `worker interrupt` acknowledges or rejects explicitly | Terminate the owning process; no thread-level acknowledgement |
| Cleanup | Idempotent `worker close` | Process exit only |

## Recovery and stale-turn demonstration

Start a background worker, then simulate an interrupted owner process or
restart the caller. Query the worker again from a new shell.

```sh
codex-axi worker list
codex-axi worker view <worker-id>
codex-axi worker send <worker-id> --message "Continue with the remaining check."
```

Pass criteria:

1. A completed or missing active turn is reconciled to a definitive terminal
   status.
2. A request to control a stale turn fails with structured `stale_active_turn`
   output; it must never guess a different turn.
3. A resumed task records the newly created active turn before accepting later
   steering or interruption.

## Native-delegation demonstration

This test proves real Codex parent-child relationships without relabeling
independent workers as subagents.

```sh
codex-axi delegate --sandbox read-only --approval deny-all \
  --message "When useful, delegate repository inspection and summarize the findings."
codex-axi agent list <root-thread-id>
```

Pass criteria: each returned child has `parent_thread_id` equal to the root
thread ID. An empty result is valid when Codex decides not to delegate; it is
not evidence that an AXI worker is a native subagent.

## Ambient-context demonstration

Install the opt-in Claude Code integration, start a fresh Claude Code session,
and confirm that its initial context contains only the current workspace's
compact AXI dashboard. This demonstrates discovery without making the caller
load an MCP schema or issue a preliminary listing call.

```sh
codex-axi setup hooks --target claude
```

Pass criteria: setup is idempotent, unrelated Claude configuration remains
unchanged, and the injected context excludes workers from other workspaces.

## Safety and output checks

Every benchmark should use `--sandbox read-only` and `--approval deny-all`
unless the scenario explicitly requires writes. Capture stdout and stderr
separately: normal CLI stdout must remain structured TOON, while diagnostic
output belongs on stderr. Verify both success paths and failure paths (daemon
absence, protocol/version mismatch, and stale active turn) before making a
compatibility claim.
