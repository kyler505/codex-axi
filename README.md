# codex-axi

An agent-native control surface that lets Claude Code, OpenCode, and other CLI agents delegate engineering work to Codex, observe it, and steer it through a compact AXI-compliant interface.

The implementation brief is in [`docs/SPEC.md`](docs/SPEC.md).

## Commands

```sh
codex-axi
codex-axi doctor
codex-axi daemon status
codex-axi task start --message "<task>"
codex-axi task list
codex-axi task view <thread>
codex-axi task steer <thread> --message "<direction>"
codex-axi task interrupt <thread>
codex-axi task resume <thread> --message "<next turn>"
codex-axi task archive <thread>
codex-axi worker start --background --message "<task>"
codex-axi worker list
codex-axi worker send <thread> --message "<direction or next turn>"
codex-axi worker follow <thread>
codex-axi worker interrupt <thread>
codex-axi worker close <thread>
codex-axi agent list <root-thread>
codex-axi delegate --message "<task>"
codex-axi setup hooks --target all
codex-axi mcp-server
```

Workers are AXI-managed ordinary Codex threads. Native subagents are displayed
only when Codex reports a real `parent_thread_id` relationship.

## Development

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest
.venv/bin/ruff check src tests
PYTHONPATH=src .venv/bin/python -m codex_axi.skill --check
```

```sh
codex-axi doctor
codex-axi daemon status
```

`doctor` never starts or installs a daemon. Start it explicitly when needed:

```sh
codex app-server daemon start
```

See [`docs/IMPLEMENTATION.md`](docs/IMPLEMENTATION.md) for the current managed
proxy compatibility probe and direct SDK fallback behavior.

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
