# Implementation notes

## Managed proxy compatibility

The specified `openai-codex SDK -> codex app-server proxy -> daemon` path is
probed first. With Codex 0.144.3, the daemon control socket requires a WebSocket
upgrade while `codex app-server proxy` is a raw byte relay and the Python SDK
uses newline-delimited JSON-RPC over stdio. A live initialize probe therefore
fails even though `daemon version` succeeds.

For non-shared operations, codex-axi uses the SDK's supported direct app-server
launch fallback. Active-turn control is delivered to the process that owns the
public SDK `TurnHandle`; codex-axi does not implement or translate app-server
protocol messages. The managed proxy remains preferred automatically whenever
its initialize probe succeeds.

## Historical native-agent hydration

Codex 0.144.3 emits `subAgentActivity` thread items that the matching
`openai-codex` 0.1.0b3 generated `ThreadItem` union cannot deserialize. Native
agent discovery therefore uses the SDK client's raw `thread/read` result only
for this compatibility case, preserving unknown items and requiring each child
to report the requested root as its `parentThreadId`. All mutations and normal
turn execution remain on public SDK methods.
