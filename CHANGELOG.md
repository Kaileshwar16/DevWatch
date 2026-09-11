# Changelog

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
