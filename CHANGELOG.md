# Changelog

## 0.3.0 — unreleased

- Add static Python function tracing by name or file:line, caller/callee navigation,
  bounded entry paths, explicit ambiguity, source previews, and the dashboard's f view.

- Distinguish passed/failed checks from error, unavailable, timeout and cancelled outcomes.
- Add structured reasons, conservative test-output classification and shared command preflight.
- Check Node script dependencies and Python environments without executing project scripts.
- Detect package managers, package-local commands and canonical Make/Just/Task/PDM/CI checks.
- Retain command provenance and heuristic alternatives; preserve user configuration precedence.
- Explain Go recursive package-discovery permission failures without silently skipping data directories.
- Show outcomes, provenance and availability in CLI, TUI, doctor, JSON and affected checks.
- Bound metadata/package discovery, cache manifest reads, isolate detector failures and add safe diagnostics.
- Close subprocess-startup cancellation races and drain shutdown output without unbounded buffering.
- Add real-tool fixtures, scale/race tests, clean-wheel smoke, security/contribution docs and release CI.

JSON schema 1 is retained with additive fields. See [release notes](RELEASE_NOTES.md)
for compatibility details and release checks. This entry is not a publication record.

## 0.2.0

- Run services and tasks concurrently, with duplicate-start protection and shutdown of all session commands.
- Search commands by name, description, or argument; inspect running and completed tasks with `a`.
- Keep separate bounded logs and stop only the selected task with `x`.
- Configure task working directories, environment overrides, descriptions, and individual timeouts.
- Check configuration, working directories, and executable availability using `--doctor`.
- Reject unknown configuration keys to surface spelling errors.
- Add JSON schema version 1; expose environment variable names without their configured values.
- Clean up POSIX process groups on CLI SIGTERM and synchronous detector timeouts; dashboard Ctrl+C, SIGTERM, and terminal hangup shut down session tasks.
- Preserve high listening ports and separate IPv4/IPv6 addresses in fallback detection.
- Keep Git detail navigation responsive during slow commands.
- Expand subprocess, CLI, and headless UI regression coverage and Linux/macOS CI.

Configuration using strings or argument arrays remains supported. Unknown keys now produce errors. New JSON command fields are additive; consumers should ignore fields they do not use. Logs remain in memory for the current dashboard session.
