"""Static command guidance shared by the home view and generated skill."""

COMMANDS = [
    "codex-axi task list",
    'codex-axi worker start --message "<task>"',
    'codex-axi delegate --message "<task>"',
]


def render_skill() -> str:
    bullets = "\n".join(f"- `{command}`" for command in COMMANDS)
    description = (
        "Delegate engineering work to Codex tasks or deterministic workers "
        "and inspect or steer their state."
    )
    return f"""---
name: codex-axi
description: {description}
---

# codex-axi

Use `codex-axi` to control Codex work in the current workspace.

{bullets}

Workers are ordinary Codex threads managed by codex-axi. They are not native Codex subagents.
"""
