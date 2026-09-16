"""Keyboard-accessible picker for detected tasks and configured services."""

from __future__ import annotations

import shlex
from collections.abc import Iterable

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from calltrail.commands import Command


class CommandsScreen(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "dismiss", "Back")]
    DEFAULT_CSS = """
    CommandsScreen { align: center middle; }
    #commands-dialog { width: 90%; max-width: 110; height: 80%; border: thick $accent; background: $surface; padding: 1 2; }
    #commands-title { height: auto; margin-bottom: 1; }
    OptionList { height: 1fr; }
    #command-search { margin-bottom: 1; }
    """

    def __init__(self, commands: Iterable[Command]):
        super().__init__()
        self.commands = list(commands)
        self._name_width = min(28, max((len(command.name) for command in self.commands), default=0))

    def compose(self) -> ComposeResult:
        with Vertical(id="commands-dialog"):
            yield Static("Commands · Enter to run · Esc to close", id="commands-title")
            yield Input(placeholder="Search commands…", id="command-search")
            yield OptionList(id="command-list")

    def _filter(self, query: str = "") -> None:
        options = self.query_one(OptionList)
        options.clear_options()
        for command in self.commands:
            if query.casefold() in f"{command.name} {command.description} {shlex.join(command.argv)}".casefold():
                port = f"  port {command.port}" if command.port else ""
                label = Text(f"{command.name:<{self._name_width}}  ")
                label.append(shlex.join(command.argv), style="dim")
                label.append(port, style="dim")
                label.append(f"\n  source: {command.provenance} · scope: {command.scope}", style="dim")
                if command.preflight and command.preflight.errors:
                    issue = command.preflight.errors[0]
                    label.append(f"\n  {issue.state.value}: {issue.summary}", style="yellow")
                if command.description:
                    label.append(f"\n{' ' * (self._name_width + 2)}{command.description}", style="dim")
                options.add_option(Option(label, id=command.name))
        if options.option_count:
            options.highlighted = 0
        self.query_one("#commands-title", Static).update(
            f"{options.option_count} commands · Enter to run · Down to browse · Esc to close")

    def on_mount(self) -> None:
        self._filter()
        self.query_one(Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self._filter(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        options = self.query_one(OptionList)
        if options.option_count:
            self.dismiss(options.get_option_at_index(options.highlighted or 0).id)

    def on_key(self, event) -> None:
        if event.key == "down" and isinstance(self.focused, Input):
            self.query_one(OptionList).focus()
            event.stop()
            event.prevent_default()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)
