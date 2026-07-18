# Runtime compatibility notes

This document records installed-runtime behavior that affects how `codex-axi`
connects to Codex. It is intentionally narrower than the public CLI contract;
run `codex-axi doctor` on the target machine for the current result.

## Connection policy

1. Use `codex app-server daemon version` as the daemon's protocol-level health
   check; Codex owns the Unix-socket WebSocket handshake used by that command.
2. Track daemon health separately from whether the installed SDK can attach to
   the shared control transport.
3. Use the shared runtime only when both capabilities are available.
4. Use the SDK's supported direct app-server launch fallback for
   non-shared operations where that does not imply cross-process live control.

The CLI never implements, translates, or reverse engineers app-server protocol
messages. The SDK remains the transport owner in either path.

## Codex 0.144.x

With Codex 0.144.3 and 0.144.4, `codex app-server daemon version` performs a
real initialize exchange over the daemon's WebSocket control socket. A
successful response is therefore authoritative daemon health, including when
the managed process was started with `--remote-control`.

The published `openai-codex` 0.1.0b3 SDK uses newline-delimited JSON-RPC over
stdio. `codex app-server proxy` is a raw byte relay to a WebSocket-framed Unix
socket, so selecting it through the SDK's command override does not create a
compatible shared transport. `doctor` reports this separately as
`shared_transport_available: false`; it does not call a remote-control daemon
a competing process.

For non-shared operations, `codex-axi` therefore uses the official SDK's direct
app-server fallback. Active-turn control remains attached to the process that
owns the public SDK `TurnHandle`; the CLI does not claim proxy-backed
cross-process control while shared attachment is unavailable.

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

`doctor` delegates authentication to `codex login status` and exposes the
current Codex-owned primary and secondary quota snapshots when the installed
SDK/runtime supports `account/rateLimits/read`. It never reads Codex's private
state files. An unavailable rate-limit snapshot is explicit and should be
treated as insufficient evidence for a caller that must gate dispatches.

Foreground `task start`, `task resume`, and `worker start` accept `--timeout`
to bound local waiting. On expiry, codex-axi interrupts the exact recorded
turn, clears its active-turn metadata, persists `interrupted`, and returns a
structured `turn_timeout` error. `task steer --timeout` bounds only the
control acknowledgement wait because steering itself does not wait for turn
completion.

Turn event capture is opt-in through `--events`. The SDK connection that owns
the active `TurnHandle` writes selected notifications to a mode-`0600` NDJSON
journal under the codex-axi state directory. `task events` and `worker events`
read that journal; `--follow --json` streams one complete JSON event per line.
Reasoning deltas are not recorded. The event sink is deliberately passive, so
serialization or filesystem failures cannot fail the turn or interfere with
timeout, steer, or interrupt timing.
Event envelopes use schema version `1`, payload records are bounded to 64 KiB,
and each NDJSON line is flushed atomically from the owning process. Snapshot
reads retain only the requested tail in memory. Followers wait for an explicit
writer-finished marker while the recorded owner process remains alive. If the
writer exits without marking completion, followers perform a bounded terminal
drain after metadata becomes terminal so a missing marker cannot leave them
blocked forever.
Unknown additive notification methods are retained as `extension: true`
envelopes with their payload omitted, since it has not been vetted for size
or sensitive content; methods containing reasoning data are excluded
regardless of version.

For lifecycle-specific verification, use the recovery, stale-turn, native
delegation, ambient-context, and structured-output checks in
[BENCHMARKS.md](BENCHMARKS.md).
