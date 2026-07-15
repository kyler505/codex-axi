# codex-axi

An agent-native control surface that lets Claude Code, OpenCode, and other CLI agents delegate engineering work to Codex, observe it, and steer it through a compact AXI-compliant interface.

The implementation brief is in [`docs/SPEC.md`](docs/SPEC.md).

## Status

Research complete. Implementation has not started.

## Intended architecture

```text
Claude Code / OpenCode / agent CLI
              |
      codex-axi CLI or MCP
              |
       openai-codex SDK
              |
   codex app-server proxy
              |
 managed Codex app-server daemon
```

The CLI is the source of truth. An optional small MCP adapter and generated Agent Skill provide additional discovery surfaces without duplicating orchestration logic.

