# 0.3.0 release notes — draft, not published

CallTrail now distinguishes checks that failed from checks that could not run.
Missing Jest/pytest prerequisites produce UNAVAILABLE; Go package-enumeration errors
produce ERROR with a discovery reason. CLI, doctor, affected checks and dashboard
share the same preflight and structured execution outcomes.

Commands carry provenance, scope, runner and availability metadata. Bounded
monorepo discovery keeps commands in the packages that define them. Simple
Make/Just/Task/PDM/CI checks are visible alongside heuristic alternatives.
Diagnostics include per-detector timings without dumping environment values or
process output. Startup cancellation now cleans up processes even if cancellation
arrives before the subprocess handle is returned.

## Compatibility

The distribution and executable are still `calltrail`. All existing configuration
keys, CLI flags and TUI shortcuts remain. Configured commands still override
detection. JSON stays at schema version 1: fields are additive, `commands` remains
a mapping, and `source` still says `configured` or `detected`; `provenance` supplies
the actual source. Raw process exit codes and CLI timeout/signal codes are retained.
CLI summaries now appear on stderr, leaving raw streamed stdout usable in scripts.

New child-package names use `name@relative/package`; alternatives receive a source
suffix, and heuristic alternatives use `fallback-test`. Detected uv runs now use
`--no-sync --offline --no-env-file --no-python-downloads`. Prepare environments
explicitly before running checks. Externally managed Python environments that cannot
be established by safe local metadata require an explicit interpreter command.
Legacy `TaskRun.status` lifecycle values (`completed`, `stopped`, `timed out`) remain
for callers; `TaskRun.result.state` provides the new execution semantics. Ambiguous
nonzero exits now report ERROR instead of FAILED, intentionally correcting the old
misleading behavior.

## Before publishing

- Review the final validation report and run the Linux/macOS CI matrix.
- Confirm the read-only live Docker/Compose smoke on the release runner.
- Review packaging metadata and this draft; run build and clean-wheel smoke.
- Review the version and changelog. No tag, push, PyPI upload or GitHub release is
  performed by the readiness tooling.

A minor pre-1.0 bump from 0.2.0 to 0.3.0 is recommended for these visible additions
and corrected outcome semantics. There are no repository tags or published-release
history in this checkout to infer a broader compatibility policy from.
