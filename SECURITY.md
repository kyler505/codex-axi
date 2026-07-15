# Security policy

## Supported versions

codex-axi is alpha software. Security fixes are made on the latest release and
the default branch; older releases are not supported.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use GitHub's private
vulnerability reporting for this repository. Include a minimal reproduction,
affected version, impact, and any suggested mitigation. Do not include Codex
credentials, transcripts, approval data, or unrelated local files.

## Trust boundary

codex-axi delegates to the installed Codex runtime and preserves its sandbox
and approval modes. It does not make repository instructions, hooks, MCP tools,
prompts, or web content trusted. Review requested permissions and use the least
privileged sandbox suitable for the task.
