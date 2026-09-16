# CallTrail / CallTrail

A terminal dashboard for your development environment. Run `calltrail` inside a project to see its languages, runtimes, Git changes, Docker containers, listening ports, and runnable tasks.

```bash
calltrail              # See your local development environment
calltrail --affected   # Explain which checks match your changes
calltrail --doctor     # Find prerequisites that prevent checks from running
```

## Why use it?

See project tools, Git changes, containers, ports and runnable commands together.
Run checks from the right package directory, keep service logs separate, and learn
whether a check failed or the environment prevented it from running.

## Install

Requires Python 3.10 or newer. Linux and macOS are the primary supported platforms; Windows support is experimental (see process-cleanup limitations below). From this checkout:

```bash
# Install in an isolated tool environment, available from any project
pipx install .

# Or install for development
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

On Windows, activate with `.venv\Scripts\activate`. Git, Docker, language runtimes, and project dependencies are separate tools: install the ones your project needs. Missing tools appear as unavailable. CallTrail does not install project dependencies or read `.env` contents.

## Use

```bash
calltrail                            # Interactive dashboard for this project
calltrail /path/to/project            # Inspect another project
calltrail --help
calltrail --doctor                   # Validate environment, dependencies and discovery
calltrail --doctor --debug           # Add safe detector timings and selection diagnostics
calltrail --status                   # Plain-text snapshot, then exit
calltrail --json                     # Machine-readable snapshot, then exit
calltrail --list-commands             # List detected scripts and configured tasks
calltrail --run test                  # Stream tests and return their exit status
calltrail --run lint --timeout 60
calltrail --run service:api           # Run a configured foreground service
calltrail --init                     # Generate .calltrail.toml; never overwrites
calltrail --interval 10              # Refresh the dashboard every 10 seconds
calltrail --interval 0               # Refresh only when requested
```

Options work with the optional project path, for example `calltrail ../api --run test`.
The nearest project marker defines the working directory, so a package inside a monorepo gets its own commands. With no marker in any ancestor, CallTrail uses the supplied directory. An invalid path or configuration produces a readable error.

The dashboard uses a compact, neutral terminal layout with subtle section dividers and aligned columns. It refreshes every five seconds. Start your API and frontend with `c`, then run tests with `t` while both services stay up. Press `a` to select a task and inspect its output; press `x` to stop that selected task. Commands run in the background and their output survives refreshes. Narrow terminals stack the panels vertically; scroll to see the full dashboard.

| Key | Action |
|-----|--------|
| `t` | Run tests |
| `c` | Search commands and services; Enter runs the first match, Down moves to the list |
| `a` | List session tasks with status, elapsed time, and exit code; Enter selects their logs |
| `i` | Impact snapshot: changed files and selection reasons; `r` runs affected checks |
| `f` | Explore possible static Python callers, callees, and entry paths |
| `x` | Stop the task whose output is currently selected |
| `r` | Refresh all panels and reload configuration |
| `g` | Git details: `s` status, `l` log, `d` staged and unstaged diff statistics |
| `d` | Docker details: `u` Compose up, `x` Compose down, `r` refresh |
| `p` | Refresh listening ports |
| `Esc` | Close a detail view or command picker |
| `q` | Quit and stop all session commands; from Git/Docker details, return to the dashboard |
| `Ctrl+C` | Quit from any screen and stop all session commands |

The dashboard runs up to 16 commands concurrently. Choosing an already-running command opens its logs instead of starting a duplicate. Choose a completed or stopped command from `c` to run it again; `a` only views logs. Each command retains its latest run, with up to 2,000 lines / roughly 512 KiB of text. Up to 50 command records are retained; older inactive records are evicted when necessary. Logs are in memory and disappear on exit. Configuration refresh applies to future runs; running commands keep their original settings. Compose `up` starts detached containers; exiting the dashboard leaves those containers running. Compose `down` explicitly stops and removes the project's containers and network, without requesting volume deletion.

## Configuration

Auto-detection works without configuration. Run `calltrail --init` to create a starter file populated with detected commands, or write `.calltrail.toml`:

```toml
[project]
name = "My API"

[commands]
test = ["python", "-m", "pytest", "-v"]
lint = "ruff check ."
format = "ruff format ."
dev = ["python", "-m", "myproject"]

[services.api]
command = ["uvicorn", "app:app", "--reload", "--port", "8000"]
port = 8000
```

For monorepos or commands needing their own settings, use a table:

```toml
[commands.check_api]
command = ["python", "-m", "pytest", "-q"]
cwd = "api"
description = "Run the API test suite"
timeout = 120
env = { APP_ENV = "test" }

[services.web]
command = ["npm", "run", "dev"]
cwd = "web"
description = "Frontend development server"
port = 5173
```

`cwd` resolves relative to the project root and selects that directory's virtual environment. `env` adds or overrides inherited environment variables; values must be strings. Do not commit secrets in project configuration. Snapshots include only the configured environment variable names (`env_keys`); command arguments and process output can still contain whatever the configured tool prints. `timeout` accepts seconds, including fractions; `0` disables it. `--timeout` overrides per-command settings. Unknown keys, invalid ports, invalid quoting, and invalid values produce errors with configuration context. Run `calltrail --doctor` to catch missing directories and executables before starting commands.

See [the full-stack example](examples/fullstack.calltrail.toml) for an API and frontend workspace.

Configured commands override detected commands with the same name. Services appear as `service:api` in the command picker and CLI. The optional port is display metadata; it does not change the command's arguments or reserve a port.

String commands support shell-like quoting. Arrays are preferable for paths containing spaces, especially on Windows. Commands execute directly, with no implicit shell: pipes, `&&`, variable expansion, globbing, and `~` expansion are not performed. For those features, configure an explicit shell command or a project script. Project commands are executable code; review a project's configuration and package scripts before running them. Discovery and refresh never run configured commands or services.

CallTrail prepends a detected `.venv`, `venv`, or `env` to `PATH`. Python test detection uses that interpreter, or a lockfile-selected uv, Poetry, PDM, or Pipenv runner. Detected uv runs disable synchronization, downloads and dotenv loading; detected Pipenv runs disable dotenv loading. Missing intended runners produce UNAVAILABLE. Preflight recognizes local virtual environments; for externally managed environments, configure an explicit interpreter. `.env` files are only detected, never loaded by CallTrail.

Tasks time out after 300 seconds unless configured otherwise; configured services have no default timeout. `--timeout 0` disables the timeout, and `--timeout SECONDS` applies to CLI or dashboard tasks. Output streams live, with a bounded recent-output buffer. Commands have no interactive stdin: run tools that prompt for input directly in your terminal. On POSIX, cancellation terminates the process group, including ordinary child processes such as reloaders. Ctrl+C stops session commands from any dashboard screen. POSIX SIGTERM and terminal hangup also shut down dashboard-owned commands; CLI SIGTERM cleans up the running command before returning. Processes that deliberately detach into another session are outside that process group. On Windows, CallTrail terminates the direct child; descendant cleanup depends on the tool.

## Change-aware checks

```bash
calltrail --affected                 # Explain which checks match current Git changes
calltrail --run-affected             # Run those checks sequentially
calltrail ../api --run-affected --timeout 60
```

Staged, unstaged, and untracked files are collected together. Renames match both the old and new paths. Clean working trees, unavailable Git, and unmatched changes produce an explanation and exit successfully without running anything. In the dashboard, press `i` to inspect the latest snapshot and `r` in that view to run its affected checks. Refresh the dashboard to collect new changes. Output and individual exit statuses remain available in the existing task/log view (`a`); `x` stops the active check and the rest of its queue.

Add explicit rules for focused checks in `.calltrail.toml`:

```toml
[commands.test_auth]
command = ["python", "-m", "pytest", "tests/auth"]
paths = ["src/auth/**", "tests/auth/**"]

[commands.test_frontend]
command = ["npm", "test"]
cwd = "frontend"
paths = ["frontend/src/**", "frontend/tests/**"]

[commands.lint]
command = ["ruff", "check", "src/auth", "tests/auth"]
paths = ["src/auth/**", "tests/auth/**"]
```

Rules are case-sensitive globs anchored at the selected project root, **not** the command's `cwd`. Use `/` on every platform. `*` matches within one path component, `?` matches one character, and `[abc]` / `[!abc]` match character classes. A whole `**` component matches zero or more components: `src/**/*.py` includes both `src/token.py` and `src/auth/token.py`. Dotfiles match normally. There is no implicit basename matching, negation, brace expansion, or Git-ignore syntax. Absolute paths, backslashes, empty patterns, `.`/`..` components, and embedded `**` (such as `foo**bar`) are rejected. Use `directory/**` for a directory tree. `paths = []` selects nothing. Configured commands without `paths` retain their normal manual behavior and are not automatically selected; services are excluded.

This first version is conservative and path-based, not a full dependency analyser, and uses no AI. Detected `test`, `lint`, `check`, `typecheck`, and `type-check` scripts (including colon variants such as `test:unit`) are candidates. Files inside a check's working directory select it. Package-local checks run before broader root checks; shared files outside known package scopes can select multiple suites. For Python, `src/auth/token.py` also looks for `tests/auth/`, `tests/test_token.py`, and `tests/auth/test_token.py` (and equivalent `test/` paths) as evidence. Automatic checks retain their full original arguments to avoid skipping indirect dependencies. Explicit rules provide narrower runs and should include shared configuration/dependencies that matter to your checks. Package discovery examines at most 512 directories to depth 4, excluding generated trees and directory symlinks. Child commands use names such as `test@api` or `test:unit@web`, with their own `cwd`. Use configured commands with `cwd` and `paths` for deeper or unusual layouts.

Each distinct invocation (arguments, directory, environment, and effective timeout) runs once per batch. Aliases may appear separately in the report, but execute once. Ordinary failures and timeouts do not stop later checks. CLI output reports each executed check's status and returns the first nonzero exit code; Ctrl+C or SIGTERM cancels the queue and cleans up the active process using the existing runner. No tests or project commands run during impact discovery.

JSON snapshots add `changed_files`, `affected_commands`, and `changes_error` while retaining schema version 1 and every existing field. Changed-file records include `path`, `index_status`, `worktree_status`, and optional `original_path`; `?` denotes untracked files. Affected entries contain `name`, `argv`, `cwd`, `matched_files`, `matched_patterns`, and structured `reasons` with a file, strategy, explanation, optional pattern, and nearby tests. Paths are relative to the selected project; shared changes outside a selected package use `../` and cannot match explicit project-root rules. Git failures also appear in `warnings`.

## Function tracing

Explore unfamiliar Python code without running the application:

```bash
calltrail trace auth/token.py:117
calltrail trace decode_token
calltrail trace AuthService.decode_token
calltrail trace auth/token.py:117 --outgoing
calltrail trace auth/token.py:117 --to-entry
calltrail trace decode_token --root /path/to/project --json
calltrail trace decode_token --to-entry --max-depth 12 --max-paths 30 --max-nodes 2000
```

CallTrail performs conservative static analysis. Results represent **possible call
relationships, not guaranteed runtime execution paths**. Tracing parses Python
source as data: it never imports project modules, evaluates decorators, executes
tests or setup.py, loads `.env`, or runs framework discovery.

The default view shows possible static callers and their callsites. `--outgoing`
shows possible callees, including unresolved calls. `--to-entry` follows resolved
edges backward to likely MAIN, TEST, CLI, or HTTP entry points. UNKNOWN means no
further resolved caller was found; it is not proof of an entry point. Cycles and
limit truncation are shown explicitly. Paths are ordered by length, then known
entry kinds. Ambiguous edges are visible but are not traversed into entry paths.

Use an exact function name, a qualified name such as `Class.method` or
`outer.inner`, or a **project-root-relative** `file.py:line`. Locations select the
innermost containing definition. Ambiguous names list candidates and require a
file/line selection. The default boundary is the nearest existing project root;
`--root` sets an explicit boundary. Other languages report that tracing is
unavailable. Existing `--json` and other dashboard/task flags are unchanged;
`trace … --json` is a separate schema-version-1 object with `kind=call_hierarchy`
and `evidence=static`. Trace exits 0 on success (including partial results with
warnings), 1 for ambiguous/missing/unsupported targets, and 2 for usage/root errors.
If your project directory is named `trace`, use `calltrail ./trace` to disambiguate.

In the dashboard press **f**, enter a query, and press Enter. With the results list
focused: Enter selects a caller/callee, **i** shows callers, **o** shows callees,
**e** shows entry paths, **b/Esc** walks back through history, **q** closes,
**/** focuses search, and **r** rebuilds the graph after edits. The detail pane
contains locations and a bounded source preview. Query letters are typed normally
while the search box has focus. The index is created only when tracing is opened,
on a worker thread, and unchanged file parses are reused across refreshes.

Python support includes ordinary imports and aliases, relative imports, direct
functions, nested functions, classes, and straightforward `self`/`cls` methods.
Reflection, callback values, dependency injection, instance type inference,
inheritance dispatch, monkey patching, framework magic, and decorator transformations
are not inferred. Lambda bodies and comprehension scopes are not resolved in v1.
Definition-time calls in decorators/defaults/annotations/bases are not modeled.
Source syntax must be supported by the Python interpreter running CallTrail.
Simple `app`/`router` route decorators are labelled as heuristics, not registered
routes. Scripts from `[project.scripts]` supply CLI labels; arbitrary configured
shell commands are not mapped to functions.

The index is bounded to 3,000 Python files, 4,000 directories, depth 30, 100,000
directory entries, 1 MiB per file, and 32 MiB total source. Generated trees,
virtual environments, symlinks and nested repositories are excluded. Git is not
required; custom `.gitignore` rules are not interpreted. Warnings identify parse,
permission and limit problems. CLI relationship output is capped at 1,000 entries;
the interactive list uses 200. No external editor is launched in v1.

See [the provider design](docs/tracing.md) for integration and future runtime plans.

## Execution outcomes

| State | Meaning |
|-------|---------|
| PASSED | The command exited zero. |
| FAILED | Positive evidence shows that tests/checks ran and reported failures. |
| ERROR | Discovery, configuration, build, permissions or runtime setup prevented completion; also used for ambiguous nonzero exits. |
| UNAVAILABLE | A required executable, dependency or working directory is missing. |
| TIMEOUT | CallTrail's configured deadline expired. |
| CANCELLED | The user stopped the command or the session was interrupted. |
| RUNNING / PENDING | The command is active or awaiting execution. |

A failed check means the check actually ran and reported failure. An unavailable/error
result means the environment or tool prevented the check from completing. A nonzero
exit alone is never sufficient to claim FAILED. Supported positive failure evidence
includes pytest, unittest assertion summaries, Jest, Go test assertions and Cargo.
Other check formats conservatively remain ERROR on nonzero exits. Raw exit codes
remain available. CLI execution summaries go to stderr; tool stdout still streams.

Preflight checks cwd, executable resolution and safely recognizable prerequisites.
For simple Node scripts it checks common local runners such as Jest; complex shell
scripts and Yarn Plug’n’Play are left to the package manager with a warning.
Doctor and execution also perform a bounded Go package-enumeration hazard check.
Unreadable runtime data is reported, never silently excluded from recursive Go checks.
Preflight is a point-in-time check, not a promise that the command will succeed.
It never installs dependencies, changes permissions or starts Docker.

Commands retain `source` (`configured` / `detected`) for compatibility and add
`provenance`, `scope`, `runner` and `preflight`. See provenance in `--list-commands`,
`--doctor`, the command picker and execution summaries. Simple Makefile, justfile,
Taskfile, PDM and single-line GitHub Actions checks are statically detected. Existing
package scripts keep priority over newly discovered canonical alternatives; explicit
`.calltrail.toml` commands win over all detection. Alternatives remain listed;
`fallback-test` identifies a heuristic alternative to a canonical test target.
No Make recipes or CI expressions execute during detection.

Node manager selection uses valid `packageManager` metadata, then pnpm/Yarn/Bun/npm
lockfiles (including npm-shrinkwrap). Scripts execute from the package that defines
them. Rust uses `cargo test` in its manifest scope. Go uses canonical project checks
where found, otherwise `go test ./...` is labelled `CallTrail heuristic (Go)`.

`--doctor` returns 0 for no meaningful problems, 1 for command/project problems,
and 2 for invalid CLI/configuration. Missing optional Git or Docker in a project
that does not use them remains informational for compatibility. A broken declared
Compose environment is a doctor problem. `--debug` prints version, platform, root,
detector timings, selected managers/environments and command provenance; it omits
environment values, command arguments and arbitrary tool output.

## Detection and scripting

| Area | Detected information |
|------|----------------------|
| Project | Nearest root, manifest name, Python/JS/TS/Go/Rust/Java, common frameworks |
| Runtime | Python, Node, Go, Rust, Java versions |
| Packages | uv, pip, Poetry, Pipenv, PDM, npm, pnpm, Yarn, Bun, Cargo, Go |
| Git | Branch, changed paths, ahead/behind counts, latest commit; supports worktrees and detached HEAD |
| Docker | Running and stopped containers; project scope when a Compose file exists, otherwise explicitly labelled host scope |
| Ports | Host TCP listeners, addresses, process names and PIDs when permitted |
| Commands | Python tests, Go/Cargo/Maven/Gradle tests, package.json scripts, static canonical checks, package scopes, config overrides and services |

Docker detection handles both JSON arrays and JSON Lines from Compose. An empty or failing Compose project never falls back to unrelated host containers. See the [Compose ps reference](https://docs.docker.com/reference/cli/docker/compose/ps/) for the underlying container query.

Port visibility depends on operating-system permissions. An empty list means no listeners were visible to CallTrail; it is not a guarantee that every port is free. Ports are host-wide and are not assumed to belong to the current project.

`--json` emits one JSON object on stdout with `schema_version` (currently `1`), `name`, `root`, `languages`, `frameworks`, `runtime`, `package_manager`, `venv`, `git`, `docker`, `ports`, `test_command`, `test_result`, `has_env`, `warnings`, and `commands`. Optional unavailable areas are null or empty; detector failures appear in `warnings`. Command entries include their name, argument vector, service flag, optional port, working directory, environment variable names, configured timeout, and description. Additional fields may be added within a schema version; consumers should ignore unknown fields. Snapshots do not execute tasks, so `test_result` is null. Commands add `provenance`, `scope`, `runner`, and `preflight`; affected entries also include preflight/provenance. Snapshot `diagnostics` records per-detector duration and failure type. Preflight-only errors use compatibility codes 127 (unavailable) or 126 (error); these are not child-process exit codes.

```bash
calltrail --json > environment.json
calltrail --run test > test-output.log 2>&1
```

Exit codes: snapshots and successful tasks return `0`; failed doctor checks return `1`; CLI/config errors return `2`; command timeouts return `124`; missing executables return `127`; Ctrl+C returns `130`; POSIX SIGTERM returns `143` and dashboard terminal hangup returns `129`. Other command failures retain the tool's exit code. Snapshot success means collection completed, even if an optional tool is unavailable. Redirected output requires `--status`, `--json`, `--doctor`, `--list-commands`, `--init`, `--run`, `--affected`, or `--run-affected`; the dashboard requires an interactive terminal.

## Troubleshooting

- **A task cannot start:** run `calltrail --doctor`; check its executable and `cwd`. Install project dependencies using your normal workflow.
- **A service exits immediately:** select it with `a` and inspect its output and exit code. Configured ports are labels, not health checks or port reservations.
- **Tests time out:** set the command's `timeout`, or use `--timeout 0` for a watch task.
- **No commands are found:** run `calltrail --init` and add commands. CallTrail does not execute Makefiles or project scripts during discovery.
- **The terminal is too small:** panels stack below 90 columns. Scroll the dashboard; use `c` and `a` for focused command and log selection.
- **Configuration refresh fails:** fix the displayed error and press `r`. The last successful snapshot and running tasks remain available.

## Development

```bash
python -m pip install -e ".[dev]"
python -m ruff check .
python -m unittest discover -s tests -v
python -m build
python scripts/smoke_wheel.py dist/calltrail-0.3.0-py3-none-any.whl
```

Tests use the standard library and Textual's headless driver. They cover CLI behavior, configuration, discovery, real Git repositories, subprocess lifecycle, and dashboard keyboard workflows. Docker actions are mocked; the suite does not start or stop your containers. CI is configured to run the suite and lint on Linux and macOS with Python 3.10, 3.12, and 3.14, plus a Linux job for the minimum supported Textual version. Tests include concurrent services, separate logs, signal cleanup, configuration errors, and task-picker keyboard workflows. A separate opt-in integration job validates live Docker/Compose using read-only queries. Every matrix job builds and smoke-tests a clean wheel installation. See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md) and the [release draft](RELEASE_NOTES.md).

The code separates discovery (`detectors/`, `discovery.py`), configuration and tasks (`config.py`, `commands.py`), subprocess lifecycle (`runner.py`), session task management (`tasks.py`), prerequisite checks (`doctor.py`), the scriptable CLI (`cli.py`), and the Textual UI (`app.py`, `widgets/`, `screens/`). Detectors return dataclasses; the CLI and UI share the same snapshot collection.

## License

MIT. See [LICENSE](LICENSE).
