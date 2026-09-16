# Security

## Supported versions

Security fixes target the latest release on `main`. Version 0.2.x is the current
release line; 0.3.0 is being prepared. Older versions have no separate backport
commitment. This is a small, best-effort project.

## Reporting a vulnerability

Use GitHub's **Report a vulnerability** option on the
[repository security page](https://github.com/Kaileshwar16/DevWatch/security) if
private reporting is enabled. If that option is unavailable, open a
[repository issue](https://github.com/Kaileshwar16/DevWatch/issues/new) asking the
maintainer for a private reporting channel. Do not include exploit details,
credentials, or private repository contents in that public request.

## Trust boundary

DevDash is a local developer tool, not a sandbox. Configured commands, package
scripts, Make/Just/Task targets, test suites, interpreter startup hooks, and tools
resolved through PATH are executable code with your user permissions. Inspect
untrusted repositories and their commands before running them. Preflight is an
availability check, not a security review or a guarantee of successful execution.

Discovery intentionally does not execute project commands, scripts, tests, Make
recipes, CI expressions, or install hooks. It reads bounded project metadata and
queries installed tools for versions, Git state, ports, and Docker state. Those
installed tools and their configuration remain part of the trust boundary.
DevDash never reads `.env` contents. Only their presence is displayed.

DevDash never installs project dependencies, runs sudo, changes permissions,
deletes runtime data, or starts Docker to repair an environment. Detected uv
commands disable environment synchronization, downloads, and dotenv loading;
detected Pipenv commands disable dotenv loading. Explicitly requested project
commands may have their own side effects, including dotenv use and network access.
Review their definitions before running them.

JSON includes environment variable names, not configured values. Debug diagnostics
omit command arguments, environment values, and raw process output. Normal command
listing, execution logs, status, and JSON may contain project-provided arguments,
paths, or text. Inspect these before sharing them. Logs are bounded and retained
in memory for the current session only.

POSIX cancellation stops the owned process group. Deliberately detached processes
are outside that group. Windows currently guarantees only direct-child cleanup.
