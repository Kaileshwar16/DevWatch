"""A quiet, explainable impact snapshot; execution stays in the app session."""

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import RichLog, Static

from devdash.changes import ChangeSet
from devdash.impact import impact_report
from devdash.models import ProjectInfo


class ImpactScreen(ModalScreen[list[str] | None]):
    BINDINGS = [Binding("escape", "dismiss", "Back"), Binding("q", "dismiss", "Back"),
                Binding("r", "run_affected", "Run affected")]
    DEFAULT_CSS = """
    ImpactScreen { align: center middle; }
    #impact-dialog { width: 90%; max-width: 110; height: 85%; padding: 1 2; }
    #impact-header { height: auto; margin-bottom: 1; }
    #impact-output { height: 1fr; }
    """

    def __init__(self, info: ProjectInfo):
        super().__init__()
        self.info = info

    def compose(self) -> ComposeResult:
        with Vertical(id="impact-dialog"):
            yield Static("Affected checks · r run affected · Esc back", id="impact-header", markup=False)
            yield RichLog(id="impact-output", wrap=True, markup=False)

    def on_mount(self) -> None:
        changes = ChangeSet(self.info.changed_files, error=self.info.changes_error)
        log = self.query_one(RichLog)
        log.write(Text(impact_report(changes, self.info.affected_commands)))
        log.focus()

    def action_run_affected(self) -> None:
        if self.info.affected_commands:
            self.dismiss([item.name for item in self.info.affected_commands])
        else:
            self.notify("No affected commands detected.")
