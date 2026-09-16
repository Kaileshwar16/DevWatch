"""Ports panel — shows listening ports with process info."""

from __future__ import annotations

from rich.text import Text
from rich.console import Group
from textual.widgets import Static

from calltrail.models import PortInfo
from calltrail.widgets.formatting import compact_table


class PortsPanel(Static):
    """Displays listening ports with PID and process name."""

    DEFAULT_CSS = """
    PortsPanel {
        height: auto;
        min-height: 8;
        padding: 1 2;
    }
    """

    def render_info(self, ports: list[PortInfo]) -> None:
        """Update the panel with port information."""
        if not ports:
            self.update(Text("No listening ports detected", style="dim"))
            return

        rows = compact_table(("PORT", "PROCESS", "PID"), (
            (str(p.port), p.process or "-", str(p.pid or "-")) for p in ports[:10]
        ))
        content = [rows]
        if len(ports) > 10:
            content.append(Text(f"+{len(ports) - 10} more", style="dim"))
        self.update(Group(*content))
