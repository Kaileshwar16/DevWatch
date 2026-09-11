"""Command-line interface for interactive use, scripts, and CI."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import signal
import shlex
import sys
from dataclasses import asdict
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from devdash import __version__
from devdash.commands import discover_commands
from devdash.config import ConfigError, DevDashConfig
from devdash.detectors.project import detect_project_name, find_project_root
from devdash.discovery import collect_project
from devdash.doctor import check_commands
from devdash.runner import run_streaming


async def _run_command(command, root: Path, timeout: float | None) -> int:
    """Forward terminal termination into cancellation so descendants are reaped."""
    task = asyncio.create_task(run_streaming(
        command.argv, command.cwd or root, lambda line: print(line, flush=True),
        command.effective_timeout(timeout), env=command.env,
    ))
    loop = asyncio.get_running_loop()
    interrupted = 0
    previous = {}

    def stop(signum: int) -> None:
        nonlocal interrupted
        if not interrupted:
            interrupted = signum
            task.cancel()

    try:
        if os.name == "posix":
            for signum in (signal.SIGINT, signal.SIGTERM):
                previous[signum] = signal.getsignal(signum)
                loop.add_signal_handler(signum, stop, signum)
        try:
            _, code = await task
            return code if code >= 0 else 128 - code
        except asyncio.CancelledError:
            if interrupted:
                return 128 + interrupted
            raise
    finally:
        for signum, handler in previous.items():
            loop.remove_signal_handler(signum)
            signal.signal(signum, handler)


def _nonnegative(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a nonnegative number") from exc
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("must be a finite, nonnegative number")
    return number


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(
        prog="devdash", description="Inspect your project, run tasks, and monitor your development environment.",
        epilog="Commands run only when requested. Use --list-commands to see detected tasks and services.",
    )
    cli.add_argument("path", nargs="?", default=".", help="project directory (default: current directory)")
    mode = cli.add_mutually_exclusive_group()
    mode.add_argument("--status", action="store_true", help="print a snapshot and exit")
    mode.add_argument("--json", action="store_true", help="print the snapshot as JSON and exit")
    mode.add_argument("--list-commands", action="store_true", help="list available tasks and services")
    mode.add_argument("--run", metavar="NAME", help="run a task or service:NAME, streaming output")
    mode.add_argument("--init", action="store_true", help="create .devdash.toml without overwriting an existing file")
    mode.add_argument("--doctor", action="store_true", help="validate configuration and task executables without running tasks")
    cli.add_argument("--timeout", type=_nonnegative, default=None, metavar="SECONDS",
                     help="task timeout; 0 disables it (default: 300 for tasks, unlimited for services)")
    cli.add_argument("--interval", type=_nonnegative, default=5.0, metavar="SECONDS",
                     help="dashboard refresh interval; 0 disables refresh (default: 5)")
    try:
        installed = version("devdash")
    except PackageNotFoundError:
        installed = __version__
    cli.add_argument("--version", action="version", version=f"%(prog)s {installed}")
    return cli


def initialize(root: Path) -> Path:
    config = DevDashConfig()
    commands = discover_commands(root, config)
    lines = ["# DevDash runs commands only when you request them.", "[project]",
             f"name = {json.dumps(detect_project_name(root), ensure_ascii=False)}", "", "[commands]"]
    for name, command in commands.items():
        lines.append(f"{json.dumps(name)} = {json.dumps(command.argv, ensure_ascii=False)}")
    lines.extend([
        '# lint = ["ruff", "check", "."]', '# format = ["ruff", "format", "."]', "",
        "# Strings use shell-like quoting, but no shell expansion or pipes.",
        "# [services.api]", '# command = ["python", "-m", "http.server", "8000"]', "# port = 8000", "",
    ])
    path = root / ".devdash.toml"
    with path.open("x", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return path


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        root = find_project_root(Path(args.path))
        if args.init:
            print(f"Created {initialize(root)}")
            return 0
        config = DevDashConfig.load(root)
        commands = discover_commands(root, config)
        if args.doctor:
            print(f"Project: {root}\nConfiguration: valid")
            checks = check_commands(root, commands)
            for check in checks:
                print(f"{'OK' if check.ok else 'FAIL'} {check.name}: {check.message}")
            if not checks:
                print("No commands detected. Run devdash --init to configure tasks.")
            print("Checks inspect working directories and executables; they do not run tasks or verify dependencies.")
            return 0 if all(check.ok for check in checks) else 1
        if args.list_commands:
            if not commands:
                print("No commands detected. Add [commands] to .devdash.toml, or run devdash --init.")
            for name, command in commands.items():
                port = f" (port {command.port})" if command.port else ""
                description = f" — {command.description}" if command.description else ""
                print(f"{name}{port}\t{shlex.join(command.argv)}{description}")
            return 0
        if args.run:
            if args.run not in commands:
                raise ValueError(f"Unknown command {args.run!r}. Use --list-commands to see available commands.")
            command = commands[args.run]
            print(f"$ {shlex.join(command.argv)}", file=sys.stderr, flush=True)
            return asyncio.run(_run_command(command, root, args.timeout))
        if args.status or args.json:
            info = asyncio.run(collect_project(root, config))
            if args.json:
                data = asdict(info)
                data["schema_version"] = 1
                data["commands"] = {name: command.public_dict() for name, command in commands.items()}
                print(json.dumps(data, default=str, ensure_ascii=False, indent=2))
            else:
                print(f"{info.name}\nPath: {info.root}\nLanguages: {', '.join(info.languages)}")
                if info.frameworks:
                    print(f"Frameworks: {', '.join(info.frameworks)}")
                print(f"Package manager: {info.package_manager or 'not detected'}")
                for runtime, value in info.runtime.items():
                    print(f"{runtime}: {value}")
                if info.git:
                    print(f"Git: {info.git.branch} ({'dirty' if info.git.dirty else 'clean'}), ahead {info.git.ahead}, behind {info.git.behind}")
                else:
                    print("Git: not a repository")
                docker = info.docker
                print(f"Docker: {'available' if docker and docker.available else 'unavailable'}")
                if docker:
                    for container in docker.containers:
                        print(f"  {container.name}: {container.state} {container.ports}")
                print("Listening ports (host): " + (", ".join(f"{p.address}:{p.port} ({p.process or '?'})" for p in info.ports) or "none detected"))
                print("Commands: " + (", ".join(commands) or "none detected"))
                for warning in info.warnings:
                    print(f"Warning: {warning}", file=sys.stderr)
            return 0
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise ValueError("The dashboard needs an interactive terminal. Use --status or --json in scripts.")
        from devdash.app import DevDashApp
        app = DevDashApp(root, interval=args.interval, timeout=args.timeout)
        app.run()
        return 128 + app.exit_signal if app.exit_signal else 0
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 0
    except (ConfigError, ValueError, OSError) as exc:
        print(f"devdash: {exc}", file=sys.stderr)
        return 2
