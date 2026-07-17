# Compatibility policy

`compatibility/manifest.json` is the machine-readable support policy. Every
combination is labeled `tested`, `fixture-tested`, `degraded`, or `unsupported`;
version proximity alone is not evidence of support.

`codex-axi doctor` reports runtime capabilities independently. Direct stdio,
daemon health, shared attachment, authentication, rate limits, thread reads,
and turn events can therefore degrade without producing a false global
"healthy" claim. Unknown additive fields are tolerated at read boundaries;
invalid required envelopes fail as `protocol_mismatch`.

The direct-stdio path is the portable baseline on macOS, Linux, and Windows.
Managed daemon probing is currently claimed only on macOS and Linux; Windows
does not emulate the Unix control socket. Turn interruption uses the SDK
`TurnHandle`, while background process termination and advisory state locks use
platform-native Python facilities.

Maintainers can run `python scripts/live_compat_smoke.py` on an authenticated
machine. It performs a read-only, deny-all task and verifies event capture. The
script is intentionally opt-in and must not run for untrusted pull requests.

## Output evolution

TOON and JSON representations are semantically equivalent views of the same
document. Existing keys retain their meaning; additive keys may appear. Event
NDJSON uses `schema_version: 1`, one flushed JSON object per line, a monotonic
turn-local `sequence`, and bounded payloads. Removing or changing a key requires
a documented deprecation cycle and a schema-version increment.
