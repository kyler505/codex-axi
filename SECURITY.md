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

Opt-in event journals may contain prompts, model output, commands, and file-change
details. They and control metadata are stored in user-private local state. Use
`codex-axi cleanup --dry-run` to inspect expired workspace state and `codex-axi
cleanup` to prune it; active turns and journals with live writers are preserved.
