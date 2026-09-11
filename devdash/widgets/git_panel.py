"""Git information panel."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from devdash.models import GitInfo


class GitPanel(Static):
    """Displays git branch, status, changes, ahead/behind, last commit."""

    DEFAULT_CSS = """
    GitPanel {
        height: auto;
        min-height: 8;
        padding: 1 2;
    }
    """

    def render_info(self, git: GitInfo | None) -> None:
        """Update the panel with git information."""
        if git is None:
            self.update(Text("Not a git repository", style="dim"))
            return

        text = Text()

        # Branch
        text.append("Branch    ", style="dim")
        text.append(git.branch, style="default")

        # Status
        text.append("\nStatus    ", style="dim")
        if git.dirty:
            text.append("dirty", style="yellow")
        else:
            text.append("clean", style="green")

        # Changes
        if git.dirty:
            text.append("\nChanges   ", style="dim")
            parts = []
            if git.modified:
                parts.append(f"~{git.modified}")
            if git.added:
                parts.append(f"+{git.added}")
            if git.deleted:
                parts.append(f"-{git.deleted}")
            if git.untracked:
                parts.append(f"?{git.untracked}")
            text.append(" ".join(parts), style="default")

        # Ahead/behind
        if git.ahead or git.behind:
            text.append("\nSync      ", style="dim")
            sync_parts = []
            if git.ahead:
                sync_parts.append(f"{git.ahead} ahead")
            if git.behind:
                sync_parts.append(f"{git.behind} behind")
            text.append(" ".join(sync_parts), style="default")

        # Last commit
        if git.last_commit:
            text.append("\nLast      ", style="dim")
            text.append(git.last_commit, style="default")

        if git.last_commit_time:
            text.append("\nWhen      ", style="dim")
            text.append(git.last_commit_time, style="dim")

        self.update(text)
