"""Docker detail screen — expanded container list with actions."""

from __future__ import annotations

import asyncio

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import RichLog, Static

from calltrail.actions.docker import compose_down, compose_up
from calltrail.detectors.docker import detect_docker, has_compose_file
from calltrail.widgets.formatting import compact_table


class DockerScreen(ModalScreen[None]):
    """Full-screen Docker container view with actions."""

    BINDINGS = [
        Binding("escape", "dismiss", "Back"),
        Binding("q", "dismiss", "Back"),
        Binding("u", "compose_up", "Up"),
        Binding("x", "compose_down", "Down"),
        Binding("r", "refresh_docker", "Refresh"),
    ]

    DEFAULT_CSS = """
    DockerScreen {
        align: center middle;
    }
    DockerScreen > #docker-container {
        width: 90%;
        height: 85%;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    DockerScreen > #docker-container > #docker-header {
        height: 3;
        dock: top;
        padding: 0 1;
    }
    DockerScreen > #docker-container > #docker-output {
        height: 1fr;
    }
    """

    def __init__(self, project_root, **kwargs):
        super().__init__(**kwargs)
        self.project_root = project_root
        self._busy = False

    def compose(self) -> ComposeResult:
        with Static(id="docker-container"):
            yield Static(
                Text("Docker  [u]up  [x]down  [r]refresh  [esc]back", style="bold"),
                id="docker-header",
            )
            yield RichLog(id="docker-output", wrap=True, markup=False, max_lines=5000)

    def on_mount(self) -> None:
        self.action_refresh_docker()

    @work(group="docker-refresh", exclusive=True)
    async def action_refresh_docker(self) -> None:
        if self._busy:
            return
        log = self.query_one("#docker-output", RichLog)
        docker = await asyncio.to_thread(detect_docker, self.project_root)
        log.clear()
        if not docker.available:
            log.write(Text(docker.error or "Docker is not available", style="red"))
            return
        if docker.error:
            log.write(Text(docker.error, style="red"))
            return

        log.write(Text(f"Scope: {docker.scope}", style="dim"))

        if not docker.containers:
            log.write(Text("No containers found", style="dim"))
            return

        log.write(compact_table(("NAME", "IMAGE", "STATE", "STATUS", "PORTS"), (
            (c.name, c.image, c.state, c.status, c.ports or "-") for c in docker.containers
        )))

    def action_compose_up(self) -> None:
        self._start_compose("up")

    def action_compose_down(self) -> None:
        self._start_compose("down")

    def _start_compose(self, action: str) -> None:
        if self._busy:
            self.notify("A Compose action is already running", severity="warning")
            return
        if not has_compose_file(self.project_root):
            self.notify("No Compose file in this project", severity="warning")
            return
        self._busy = True
        self.workers.cancel_group(self, "docker-refresh")
        self.run_worker(self._run_compose_action(action), group="compose")

    async def _run_compose_action(self, action: str) -> None:
        log = self.query_one("#docker-output", RichLog)
        log.write(Text(f"\n$ docker compose {action}" + (" -d" if action == "up" else ""), style="bold"))
        try:
            output, rc = await (compose_up(self.project_root) if action == "up" else compose_down(self.project_root))
            log.write(Text(output))
            log.write(Text(f"Exit {rc} · [r] refresh containers", style="green" if rc == 0 else "red"))
            self.notify(f"Compose {action}: exit {rc}", severity="information" if rc == 0 else "error")
        finally:
            self._busy = False
