"""Inspect and select running commands and retained session output."""

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from devdash.tasks import TaskManager


class TasksScreen(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "dismiss", "Back")]
    DEFAULT_CSS = """
    TasksScreen { align: center middle; }
    #tasks-dialog { width: 90%; max-width: 110; height: 80%; border: thick $accent; background: $surface; padding: 1 2; }
    #tasks-title { height: auto; margin-bottom: 1; }
    #task-list { height: 1fr; }
    """

    def __init__(self, manager: TaskManager):
        super().__init__()
        self.manager = manager

    def compose(self) -> ComposeResult:
        with Vertical(id="tasks-dialog"):
            yield Static("Session tasks · Enter to view output · Esc to close", id="tasks-title")
            yield OptionList(id="task-list")

    def on_mount(self) -> None:
        self.refresh_tasks()
        self.query_one(OptionList).focus()
        self.set_interval(1, self.refresh_tasks)

    def refresh_tasks(self) -> None:
        options = self.query_one(OptionList)
        selected = options.highlighted
        options.clear_options()
        for name, run in self.manager.runs.items():
            code = f"exit {run.returncode}" if run.returncode is not None else ""
            label = Text(f"{name:<24}  {run.status:<10}  {run.duration:>6.1f}s  {code}")
            options.add_option(Option(label, id=name))
        if options.option_count:
            options.highlighted = min(selected or 0, options.option_count - 1)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)
