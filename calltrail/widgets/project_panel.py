"""Project information panel."""

from __future__ import annotations
import os

from rich.text import Text
from textual.widgets import Static

from calltrail.models import ProjectInfo


class ProjectPanel(Static):
    """Displays project name, path, language, runtime, package manager, venv."""

    DEFAULT_CSS = """
    ProjectPanel {
        height: auto;
        min-height: 8;
        padding: 1 2;
    }
    """

    def render_info(self, info: ProjectInfo) -> None:
        """Update the panel with project information."""
        text = Text()

        rows = [
            ("Path", self._shorten_path(str(info.root))),
            ("Language", ", ".join(info.languages) if info.languages else "—"),
        ]

        # Runtime versions
        for label, version in info.runtime.items():
            rows.append((label, version))

        if info.venv:
            rows.append(("Env", info.venv))

        if info.package_manager:
            rows.append(("Package", info.package_manager))

        if info.frameworks:
            rows.append(("Framework", ", ".join(info.frameworks)))

        if info.has_env:
            rows.append(("Config", ".env detected"))

        # Render rows with aligned labels
        max_label = max(len(r[0]) for r in rows) if rows else 0
        for i, (label, value) in enumerate(rows):
            if i > 0:
                text.append("\n")
            text.append(f"{label:<{max_label}}  ", style="dim")
            text.append(value, style="default")

        self.update(text)

    @staticmethod
    def _shorten_path(path: str) -> str:
        """Replace home directory with ~."""
        from pathlib import Path

        home = str(Path.home())
        if path == home or path.startswith(home + os.sep):
            return "~" + path[len(home):]
        return path
