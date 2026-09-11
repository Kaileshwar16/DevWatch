"""Docker panel — shows container status."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from devdash.models import DockerInfo
from devdash.widgets.formatting import compact_table
from rich.console import Group


class DockerPanel(Static):
    """Displays Docker containers with status and ports."""

    DEFAULT_CSS = """
    DockerPanel {
        height: auto;
        min-height: 8;
        padding: 1 2;
    }
    """

    def render_info(self, docker: DockerInfo | None) -> None:
        """Update the panel with Docker information."""
        if docker is None or not docker.available:
            self.update(Text("Docker unavailable", style="dim"))
            return

        if docker.error:
            self.update(Text(docker.error, style="yellow"))
            return

        if not docker.containers:
            text = Text("No containers found", style="dim")
            if docker.compose_file:
                text.append("\nCompose file detected", style="dim")
            self.update(text)
            return

        rows = compact_table(("NAME", "STATE", "PORTS"), (
            (c.name, c.state.lower(), c.ports or "-") for c in docker.containers[:8]
        ))
        content = [rows]
        if len(docker.containers) > 8:
            content.append(Text(f"+{len(docker.containers) - 8} more  (d to view all)", style="dim"))
        self.update(Group(*content))
