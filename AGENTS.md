# Repository guidance

Read `docs/SPEC.md` before making architectural or implementation decisions.

This is an agent-facing CLI. Follow the locally installed `axi` skill and the current TOON specification for stdout. Keep stdout structured and token-efficient; send diagnostics and progress to stderr.

Use the official `openai-codex` Python SDK and the managed Codex app-server daemon/proxy instead of implementing a custom app-server transport or process manager. Treat the CLI as the source of truth and keep any MCP adapter thin.

Preserve the distinction between:

- `worker`: a deterministic, AXI-managed Codex thread.
- native `subagent`: a child spawned and managed by a parent Codex agent.

Do not describe independent worker threads as native Codex subagents.

Prefer narrow vertical slices with tests. Validate behavior against the installed Codex runtime, including protocol/version mismatches, daemon absence, stale active turns, and interrupted work.

