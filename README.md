# DevDash

A terminal dashboard for your development environment. Run `devdash` inside a project to see its languages, runtimes, Git changes, Docker containers, listening ports, and runnable tasks.

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

On Windows, activate with `.venv\Scripts\activate`. Git, Docker, language runtimes, and project dependencies are separate tools: install the ones your project needs. Missing tools appear as unavailable. DevDash does not install project dependencies or read `.env` contents.

## Use

```bash
devdash                            # Interactive dashboard for this project
devdash /path/to/project            # Inspect another project
devdash --help
devdash --doctor                   # Check configuration, task paths, and executables
devdash --status                   # Plain-text snapshot, then exit
devdash --json                     # Machine-readable snapshot, then exit
devdash --list-commands             # List detected scripts and configured tasks
devdash --run test                  # Stream tests and return their exit status
devdash --run lint --timeout 60
devdash --run service:api           # Run a configured foreground service
devdash --init                     # Generate .devdash.toml; never overwrites
devdash --interval 10              # Refresh the dashboard every 10 seconds
devdash --interval 0               # Refresh only when requested
```

Options work with the optional project path, for example `devdash ../api --run test`.
The nearest project marker defines the working directory, so a package inside a monorepo gets its own commands. With no marker in any ancestor, DevDash uses the supplied directory. An invalid path or configuration produces a readable error.

The dashboard uses a compact, neutral terminal layout with subtle section dividers and aligned columns. It refreshes every five seconds. Start your API and frontend with `c`, then run tests with `t` while both services stay up. Press `a` to select a task and inspect its output; press `x` to stop that selected task. Commands run in the background and their output survives refreshes. Narrow terminals stack the panels vertically; scroll to see the full dashboard.

| Key | Action |
|-----|--------|
| `t` | Run tests |
| `c` | Search commands and services; Enter runs the first match, Down moves to the list |
| `a` | List session tasks with status, elapsed time, and exit code; Enter selects their logs |
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

Auto-detection works without configuration. Run `devdash --init` to create a starter file populated with detected commands, or write `.devdash.toml`:

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

`cwd` resolves relative to the project root and selects that directory's virtual environment. `env` adds or overrides inherited environment variables; values must be strings. Do not commit secrets in project configuration. Snapshots include only the configured environment variable names (`env_keys`); command arguments and process output can still contain whatever the configured tool prints. `timeout` accepts seconds, including fractions; `0` disables it. `--timeout` overrides per-command settings. Unknown keys, invalid ports, invalid quoting, and invalid values produce errors with configuration context. Run `devdash --doctor` to catch missing directories and executables before starting commands.

See [the full-stack example](examples/fullstack.devdash.toml) for an API and frontend workspace.

Configured commands override detected commands with the same name. Services appear as `service:api` in the command picker and CLI. The optional port is display metadata; it does not change the command's arguments or reserve a port.

String commands support shell-like quoting. Arrays are preferable for paths containing spaces, especially on Windows. Commands execute directly, with no implicit shell: pipes, `&&`, variable expansion, globbing, and `~` expansion are not performed. For those features, configure an explicit shell command or a project script. Project commands are executable code; review a project's configuration and package scripts before running them. Discovery and refresh never run configured commands or services.

DevDash prepends a detected `.venv`, `venv`, or `env` to `PATH`. Python test detection uses that interpreter, or a lockfile-selected `uv`, Poetry, PDM, or Pipenv runner. The project controls what these package managers do when explicitly invoked. `.env` files are only detected, never loaded.

Tasks time out after 300 seconds unless configured otherwise; configured services have no default timeout. `--timeout 0` disables the timeout, and `--timeout SECONDS` applies to CLI or dashboard tasks. Output streams live, with a bounded recent-output buffer. Commands have no interactive stdin: run tools that prompt for input directly in your terminal. On POSIX, cancellation terminates the process group, including ordinary child processes such as reloaders. Ctrl+C stops session commands from any dashboard screen. POSIX SIGTERM and terminal hangup also shut down dashboard-owned commands; CLI SIGTERM cleans up the running command before returning. Processes that deliberately detach into another session are outside that process group. On Windows, DevDash terminates the direct child; descendant cleanup depends on the tool.

## Detection and scripting

| Area | Detected information |
|------|----------------------|
| Project | Nearest root, manifest name, Python/JS/TS/Go/Rust/Java, common frameworks |
| Runtime | Python, Node, Go, Rust, Java versions |
| Packages | uv, pip, Poetry, Pipenv, PDM, npm, pnpm, Yarn, Bun, Cargo, Go |
| Git | Branch, changed paths, ahead/behind counts, latest commit; supports worktrees and detached HEAD |
| Docker | Running and stopped containers; project scope when a Compose file exists, otherwise explicitly labelled host scope |
| Ports | Host TCP listeners, addresses, process names and PIDs when permitted |
| Commands | Python tests, Go/Cargo/Maven/Gradle tests, package.json scripts, config overrides and services |

Docker detection handles both JSON arrays and JSON Lines from Compose. An empty or failing Compose project never falls back to unrelated host containers. See the [Compose ps reference](https://docs.docker.com/reference/cli/docker/compose/ps/) for the underlying container query.

Port visibility depends on operating-system permissions. An empty list means no listeners were visible to DevDash; it is not a guarantee that every port is free. Ports are host-wide and are not assumed to belong to the current project.

`--json` emits one JSON object on stdout with `schema_version` (currently `1`), `name`, `root`, `languages`, `frameworks`, `runtime`, `package_manager`, `venv`, `git`, `docker`, `ports`, `test_command`, `test_result`, `has_env`, `warnings`, and `commands`. Optional unavailable areas are null or empty; detector failures appear in `warnings`. Command entries include their name, argument vector, service flag, optional port, working directory, environment variable names, configured timeout, and description. Additional fields may be added within a schema version; consumers should ignore unknown fields. Snapshots do not execute tasks, so `test_result` is null.

```bash
devdash --json > environment.json
devdash --run test > test-output.log 2>&1
```

Exit codes: snapshots and successful tasks return `0`; failed doctor checks return `1`; CLI/config errors return `2`; command timeouts return `124`; missing executables return `127`; Ctrl+C returns `130`; POSIX SIGTERM returns `143` and dashboard terminal hangup returns `129`. Other command failures retain the tool's exit code. Snapshot success means collection completed, even if an optional tool is unavailable. Redirected output requires `--status`, `--json`, `--doctor`, `--list-commands`, `--init`, or `--run`; the dashboard requires an interactive terminal.

## Troubleshooting

- **A task cannot start:** run `devdash --doctor`; check its executable and `cwd`. Install project dependencies using your normal workflow.
- **A service exits immediately:** select it with `a` and inspect its output and exit code. Configured ports are labels, not health checks or port reservations.
- **Tests time out:** set the command's `timeout`, or use `--timeout 0` for a watch task.
- **No commands are found:** run `devdash --init` and add commands. DevDash does not execute Makefiles or project scripts during discovery.
- **The terminal is too small:** panels stack below 90 columns. Scroll the dashboard; use `c` and `a` for focused command and log selection.
- **Configuration refresh fails:** fix the displayed error and press `r`. The last successful snapshot and running tasks remain available.

## Development

```bash
python -m pip install -e ".[dev]"
python -m ruff check .
python -m unittest discover -s tests -v
python -m pip wheel . --no-deps --wheel-dir dist
```

Tests use the standard library and Textual's headless driver. They cover CLI behavior, configuration, discovery, real Git repositories, subprocess lifecycle, and dashboard keyboard workflows. Docker actions are mocked; the suite does not start or stop your containers. CI is configured to run the suite and lint on Linux and macOS with Python 3.10, 3.12, and 3.14, plus a Linux job for the minimum supported Textual version. Tests include concurrent services, separate logs, signal cleanup, configuration errors, and task-picker keyboard workflows. Docker actions are mocked; live Docker daemon compatibility still needs release smoke testing.

The code separates discovery (`detectors/`, `discovery.py`), configuration and tasks (`config.py`, `commands.py`), subprocess lifecycle (`runner.py`), session task management (`tasks.py`), prerequisite checks (`doctor.py`), the scriptable CLI (`cli.py`), and the Textual UI (`app.py`, `widgets/`, `screens/`). Detectors return dataclasses; the CLI and UI share the same snapshot collection.

## License

MIT. See [LICENSE](LICENSE).
