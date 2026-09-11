"""Git detail screen — expanded git info with log and diff."""

from __future__ import annotations

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import RichLog, Static

from devdash.actions.git import git_diff_stat, git_log_short, git_status


class GitScreen(ModalScreen[None]):
    """Full-screen git information view."""

    BINDINGS = [
        Binding("escape", "dismiss", "Back"),
        Binding("q", "dismiss", "Back"),
        Binding("s", "show_status", "Status"),
        Binding("l", "show_log", "Log"),
        Binding("d", "show_diff", "Diff"),
    ]

    DEFAULT_CSS = """
    GitScreen {
        align: center middle;
    }
    GitScreen > #git-container {
        width: 90%;
        height: 85%;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    GitScreen > #git-container > #git-header {
        height: 3;
        dock: top;
        padding: 0 1;
    }
    GitScreen > #git-container > #git-output {
        height: 1fr;
    }
    """

    def __init__(self, project_root, **kwargs):
        super().__init__(**kwargs)
        self.project_root = project_root

    def compose(self) -> ComposeResult:
        with Static(id="git-container"):
            yield Static(
                Text("Git  [s]status  [l]log  [d]diff  [esc]back", style="bold"),
                id="git-header",
            )
            yield RichLog(id="git-output", wrap=True, markup=False, max_lines=5000)

    def on_mount(self) -> None:
        self.action_show_status()

    @work(group="git-view", exclusive=True)
    async def action_show_status(self) -> None:
        log = self.query_one("#git-output", RichLog)
        log.clear()
        log.write(Text("$ git status\n", style="bold"))
        output, _ = await git_status(self.project_root)
        for line in output.splitlines():
            log.write(line)

    @work(group="git-view", exclusive=True)
    async def action_show_log(self) -> None:
        log = self.query_one("#git-output", RichLog)
        log.clear()
        log.write(Text("$ git log --oneline\n", style="bold"))
        output, _ = await git_log_short(self.project_root)
        for line in output.splitlines():
            log.write(line)

    @work(group="git-view", exclusive=True)
    async def action_show_diff(self) -> None:
        log = self.query_one("#git-output", RichLog)
        log.clear()
        log.write(Text("$ git diff --stat\n", style="bold"))
        output, _ = await git_diff_stat(self.project_root)
        for line in output.splitlines():
            log.write(line)
