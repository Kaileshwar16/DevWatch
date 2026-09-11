"""Interactive project dashboard with responsive background tasks."""

from __future__ import annotations

import asyncio
import os
import signal
import threading
import time
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Footer, Static

from devdash.actions.tests import _parse_results
from devdash.commands import Command, discover_commands
from devdash.config import DevDashConfig
from devdash.detectors.ports import detect_ports
from devdash.detectors.project import find_project_root
from devdash.discovery import collect_project
from devdash.models import ProjectInfo, TestResult
from devdash.tasks import TaskManager, TaskRun
from devdash.screens.tasks import TasksScreen
from devdash.screens.commands import CommandsScreen
from devdash.screens.docker import DockerScreen
from devdash.screens.git import GitScreen
from devdash.widgets.docker_panel import DockerPanel
from devdash.widgets.git_panel import GitPanel
from devdash.widgets.ports_panel import PortsPanel
from devdash.widgets.project_panel import ProjectPanel
from devdash.widgets.test_panel import TestPanel


class DevDashApp(App):
    """Read-only discovery; commands run only after a user action."""

    TITLE = "DevDash"
    SUB_TITLE = "Development Dashboard"
    ENABLE_COMMAND_PALETTE = False

    CSS = """
    Screen {
        background: #101010;
        color: #d4d4d4;
    }

    #titlebar {
        dock: top;
        height: 1;
        margin: 1 2;
    }

    Footer {
        background: #101010;
        color: #909090;
        padding: 0 1;
        scrollbar-size: 0 0;
    }
    FooterKey { background: #101010; color: #909090; }
    FooterKey > .footer-key--key { background: #262626; color: #d4d4d4; }
    FooterKey > .footer-key--description { color: #909090; }
    FooterKey:hover { background: #262626; }

    #dashboard { height: 1fr; padding: 0 1; }
    #top-row, #middle-row { height: auto; }
    #dashboard.narrow #top-row, #dashboard.narrow #middle-row {
        layout: vertical;
        height: auto;
    }

    ProjectPanel, GitPanel, PortsPanel, DockerPanel {
        width: 1fr;
        border: none;
        border-top: solid #383838;
        border-title-color: #d4d4d4;
        border-title-style: bold;
        background: #101010;
        margin: 0 1 1 1;
        padding: 0;
        min-height: 5;
    }
    #activity { height: auto; padding: 0 1; color: #909090; margin-bottom: 1; }
    TestPanel {
        border: none;
        border-top: solid #383838;
        border-title-color: #d4d4d4;
        border-title-style: bold;
        background: #101010;
        margin: 0 1;
        padding: 0;
        min-height: 8;
    }
    #dashboard, TestPanel, OptionList, RichLog {
        scrollbar-size: 1 1;
        scrollbar-background: #101010;
        scrollbar-color: #383838;
        scrollbar-color-hover: #666666;
        scrollbar-color-active: #909090;
    }

    CommandsScreen, TasksScreen, GitScreen, DockerScreen {
        background: #101010 85%;
        align: center middle;
    }
    #commands-dialog, #tasks-dialog, #git-container, #docker-container {
        width: 90%;
        max-width: 110;
        height: 85%;
        border: solid #505050;
        background: #101010;
        color: #d4d4d4;
        padding: 1 2;
    }
    #command-search {
        background: #101010;
        color: #d4d4d4;
        border: none;
        border-bottom: solid #505050;
        padding: 0;
        height: 2;
    }
    #command-search:focus { border-bottom: solid #909090; }
    #command-list, #task-list {
        background: #101010;
        color: #d4d4d4;
        border: none;
        padding: 0;
    }
    #command-list > .option-list--option, #task-list > .option-list--option { padding: 0 1; }
    #command-list > .option-list--option-highlighted, #task-list > .option-list--option-highlighted {
        background: #303030;
        color: #ffffff;
        text-style: none;
    }
    #command-list > .option-list--option-hover, #task-list > .option-list--option-hover {
        background: #202020;
    }
    #git-header, #docker-header { color: #d4d4d4; }
    """

    BINDINGS = [
        Binding("t", "run_tests", "Tests"),
        Binding("c", "commands", "Commands"),
        Binding("x", "stop_command", "Stop"),
        Binding("a", "tasks", "Tasks / logs"),
        Binding("r", "refresh", "Refresh"),
        Binding("g", "git_view", "Git"),
        Binding("d", "docker_view", "Docker"),
        Binding("p", "ports_refresh", "Ports"),
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "interrupt", "Quit", show=False, priority=True),
    ]

    def __init__(self, target_path: Path | None = None, *, interval: float = 5, timeout: float | None = None):
        super().__init__()
        self._target_path = target_path
        self._interval = interval
        self._timeout = timeout
        self._info = ProjectInfo()
        self._config = DevDashConfig()
        self._commands: dict[str, Command] = {}
        self._command_task: asyncio.Task | None = None
        self._manager: TaskManager | None = None
        self._selected_run: str | None = None
        self._signal_handlers: dict = {}
        self._shutdown_task: asyncio.Task | None = None
        self.exit_signal = 0
        self._refreshing = False
        self._project_ready = False
        self._has_output = False
        self._last_error = ""

    def compose(self) -> ComposeResult:
        yield Static("devdash", id="titlebar", markup=False)
        with VerticalScroll(id="dashboard"):
            with Horizontal(id="top-row"):
                yield ProjectPanel(id="project-panel")
                yield GitPanel(id="git-panel")
            with Horizontal(id="middle-row"):
                yield PortsPanel(id="ports-panel")
                yield DockerPanel(id="docker-panel")
            yield Static("Detecting project…", id="activity", markup=False)
            yield TestPanel(id="test-panel", wrap=True, highlight=False, markup=False, max_lines=5000)
        yield Footer()

    def on_mount(self) -> None:
        if os.name == "posix" and threading.current_thread() is threading.main_thread():
            loop = asyncio.get_running_loop()
            for signum in (signal.SIGTERM, signal.SIGHUP):
                self._signal_handlers[signum] = signal.getsignal(signum)
                loop.add_signal_handler(signum, self._handle_signal, signum)
        self.project_panel = self.query_one(ProjectPanel)
        self.git_panel = self.query_one(GitPanel)
        self.ports_panel = self.query_one(PortsPanel)
        self.docker_panel = self.query_one(DockerPanel)
        self.output_panel = self.query_one(TestPanel)
        self.activity = self.query_one("#activity", Static)
        self.project_panel.border_title = "Project"
        self.output_panel.border_title = "Output"
        self.action_refresh()
        if self._interval:
            self.set_interval(self._interval, self.action_auto_refresh)

    def on_resize(self, event) -> None:
        dashboards = self.query("#dashboard")
        if dashboards:
            dashboards.first().set_class(event.size.width < 90, "narrow")

    async def _detect_all(self, manual: bool = False) -> None:
        if self._refreshing:
            return
        self._refreshing = True
        try:
            root = find_project_root(self._target_path)
            config = DevDashConfig.load(root)
            info = await collect_project(root, config)
            commands = discover_commands(root, config)
            info.test_result = self._info.test_result
            self._info, self._config, self._commands = info, config, commands
            if self._manager is None:
                self._manager = TaskManager(root, self._timeout, self._task_changed)
            self._project_ready = True
            self._last_error = ""
            self._update_panels()
            if manual:
                self.notify("Dashboard refreshed")
        except Exception as exc:
            message = str(exc)
            if manual or message != self._last_error:
                self.notify(message, severity="error", timeout=8)
            self._last_error = message
            self.activity.update(Text(f"Refresh failed: {message}", style="red"))
        finally:
            self._refreshing = False

    def _update_panels(self) -> None:
        info = self._info
        self.project_panel.border_title = "Project"
        self.project_panel.render_info(info)
        self.git_panel.border_title = "Git"
        self.git_panel.render_info(info.git)
        self.ports_panel.border_title = f"Host ports ({len(info.ports)})"
        self.ports_panel.render_info(info.ports)
        scope = info.docker.scope if info.docker else "host"
        count = len(info.docker.containers) if info.docker else 0
        self.docker_panel.border_title = f"Docker · {scope} ({count})"
        self.docker_panel.render_info(info.docker)
        if not self._has_output:
            self.output_panel.show_waiting(info.test_command)

        refresh = f"auto {self._interval:g}s" if self._interval else "manual refresh"
        running = sum(run.status == "running" for run in self._manager.runs.values()) if self._manager else 0
        status = f"{len(self._commands)} commands · {running} running · {refresh} · updated {time.strftime('%H:%M:%S')}"
        if info.warnings:
            status += " · " + " | ".join(info.warnings)
        self.activity.update(Text(status))
        title = Text("devdash", style="bold")
        title.append(f"  /  {info.name}")
        if info.git:
            title.append(f"  ({info.git.branch})", style="dim")
        self.query_one("#titlebar", Static).update(title)
        self.title = f"DevDash — {info.name}"
        self.sub_title = info.git.branch if info.git else "Development Dashboard"

    def action_run_tests(self) -> None:
        self._start_command("test")

    def action_commands(self) -> None:
        if not self._commands:
            self.notify("No commands detected. Add [commands] to .devdash.toml.", severity="warning")
            return
        self.push_screen(CommandsScreen(self._commands.values()), self._start_command)

    def _start_command(self, name: str | None) -> None:
        if name is None or self._manager is None:
            return
        if name not in self._commands:
            self.notify("No test command detected. Add [commands] test to .devdash.toml.", severity="warning")
            return
        try:
            run = self._manager.start(self._commands[name])
        except ValueError as exc:
            self.notify(str(exc), severity="warning")
            return
        self._command_task = run.task
        self._select_run(name)
        self._update_panels()

    def action_tasks(self) -> None:
        if not self._manager or not self._manager.runs:
            self.notify("No tasks yet. Press c to run a command or service.")
            return
        self.push_screen(TasksScreen(self._manager), self._select_run)

    def _select_run(self, name: str | None) -> None:
        if not name or not self._manager or name not in self._manager.runs:
            return
        self._selected_run = name
        self._has_output = True
        run = self._manager.runs[name]
        self._command_task = run.task
        self.output_panel.show_running(run.command.argv)
        if run.truncated:
            self.output_panel.append_line("[earlier output truncated]")
        for line in run.lines:
            self.output_panel.append_line(line)
        self._render_run_status(run)
        self.output_panel.scroll_visible()

    def _render_run_status(self, run: TaskRun) -> None:
        code = f" · exit {run.returncode}" if run.returncode is not None else ""
        self.output_panel.border_title = Text(f"{run.command.name} · {run.status}{code}")
        if run.status != "running":
            self.output_panel.write(Text(f"{run.status.capitalize()}{code} · {run.duration:.2f}s"))

    def _task_changed(self, run: TaskRun, line: str | None) -> None:
        if line is not None:
            if self._selected_run == run.command.name:
                self.output_panel.append_line(line)
            return
        if run.command.name == "test" and run.returncode is not None:
            result = TestResult(command=run.command.argv, output="\n".join(run.lines),
                                success=run.returncode == 0, returncode=run.returncode,
                                duration=f"{run.duration:.2f}s")
            _parse_results(result, result.output)
            self._info.test_result = result
            if self._selected_run == "test":
                self.output_panel.show_result(result)
        if self._selected_run == run.command.name:
            self._render_run_status(run)
        if self._manager and not self._manager.closing:
            self._update_panels()
            self.notify(f"{run.command.name}: {run.status}",
                        severity="error" if run.status in ("failed", "timed out") else "information")

    async def action_stop_command(self) -> None:
        if self._manager and self._selected_run:
            await self._manager.stop(self._selected_run)

    async def action_quit(self) -> None:
        if self._manager:
            await self._manager.shutdown()
        self.exit()

    def _handle_signal(self, signum: int) -> None:
        if self._shutdown_task is None:
            self.exit_signal = signum
            self._shutdown_task = asyncio.create_task(self.action_quit())

    def action_interrupt(self) -> None:
        self._handle_signal(signal.SIGINT)

    async def on_unmount(self) -> None:
        if self._manager:
            await self._manager.shutdown()
        loop = asyncio.get_running_loop()
        for signum, handler in self._signal_handlers.items():
            loop.remove_signal_handler(signum)
            signal.signal(signum, handler)
        self._signal_handlers.clear()

    def action_refresh(self) -> None:
        self.run_worker(self._detect_all(manual=True), group="refresh", exit_on_error=False)

    def action_auto_refresh(self) -> None:
        self.run_worker(self._detect_all(), group="refresh", exit_on_error=False)

    def _detail_closed(self, result=None) -> None:
        self.action_auto_refresh()

    def action_git_view(self) -> None:
        if self._info.git is None:
            self.notify("Not a git repository", severity="warning")
            return
        self.push_screen(GitScreen(self._info.root), self._detail_closed)

    def action_docker_view(self) -> None:
        if self._project_ready:
            self.push_screen(DockerScreen(self._info.root), self._detail_closed)

    async def action_ports_refresh(self) -> None:
        if self._project_ready:
            self._info.ports = await asyncio.to_thread(detect_ports, self._info.root)
            self.ports_panel.border_title = f"Host ports ({len(self._info.ports)})"
            self.ports_panel.render_info(self._info.ports)


def main() -> int:
    """Compatibility for existing editable installs."""
    from devdash.cli import main as cli_main
    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
