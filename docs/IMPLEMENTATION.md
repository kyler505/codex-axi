# Runtime compatibility notes

This document records installed-runtime behavior that affects how `codex-axi`
connects to Codex. It is intentionally narrower than the public CLI contract;
run `codex-axi doctor` on the target machine for the current result.

## Connection policy

1. Probe the managed `openai-codex SDK -> codex app-server proxy -> daemon`
   path with a protocol-level health check.
2. Use that shared runtime when the check succeeds.
3. Report the incompatibility when it fails.
4. Use the SDK's supported direct app-server launch fallback only for
   non-shared operations where that does not imply cross-process live control.

The CLI never implements, translates, or reverse engineers app-server protocol
messages. The SDK remains the transport owner in either path.

## Codex 0.144.3

With Codex 0.144.3, `codex app-server daemon version` can succeed while a live
initialize probe fails: the daemon control socket requires a WebSocket upgrade,
`codex app-server proxy` is a raw byte relay, and the Python SDK uses
newline-delimited JSON-RPC over stdio. This is a protocol mismatch, not proof
that the daemon is unavailable.

For non-shared operations, `codex-axi` therefore uses the official SDK's direct
app-server fallback. Active-turn control remains attached to the process that
owns the public SDK `TurnHandle`; the CLI does not claim proxy-backed
cross-process control when that health check has failed.

## Historical native-agent hydration

Codex 0.144.3 can emit `subAgentActivity` thread items that the matching
`openai-codex` 0.1.0b3 generated `ThreadItem` union cannot deserialize.
For that compatibility case only, native-agent discovery reads the SDK client's
raw `thread/read` result so unknown items survive hydration. A returned child
must still identify the requested root via `parentThreadId` before the CLI calls
it a native subagent.

All mutations and normal turn execution stay on public SDK methods. AXI workers
remain ordinary externally managed threads and are never used to fill a gap in
native-agent discovery.

## Operational checks

Run these after installing a new Codex version or when behavior changes:

```sh
codex-axi doctor
codex-axi daemon status
codex-axi task start --message "Reply with OK" --sandbox read-only --approval deny-all
```

For lifecycle-specific verification, use the recovery, stale-turn, native
delegation, ambient-context, and structured-output checks in
[BENCHMARKS.md](BENCHMARKS.md).
