"""Test output panel — streams test results with RichLog."""

from __future__ import annotations
import shlex

from rich.text import Text
from textual.widgets import RichLog

from devdash.models import TestResult


class TestPanel(RichLog):
    """Displays test command output streamed in real-time."""

    DEFAULT_CSS = """
    TestPanel {
        height: 1fr;
        min-height: 6;
        padding: 0 1;
    }
    """

    def show_waiting(self, command: list[str] | None) -> None:
        """Show the waiting state before tests run."""
        self.clear()
        self.write(Text("c  Run a command or service    a  View task logs", style="dim"))
        if command:
            self.write(Text(f"t  Run tests: {shlex.join(command)}", style="dim"))
        else:
            self.write(Text("No test command detected", style="dim"))
            self.write(Text("Add [commands] test = '...' to .devdash.toml", style="dim"))

    def show_running(self, command: list[str]) -> None:
        """Show that tests are currently running."""
        self.clear()
        self.write(Text(f"$ {shlex.join(command)}", style="bold"))
        self.write(Text(""))

    def append_line(self, line: str) -> None:
        """Append a line of test output."""
        text = Text.from_ansi(line)

        self.write(text)

    def show_result(self, result: TestResult) -> None:
        """Show the final test result summary."""
        self.write(Text(""))

        if result.success:
            summary = Text("PASS", style="bold green")
        else:
            summary = Text("FAIL", style="bold red")

        if result.passed or result.failed or result.errors:
            summary.append(f"  {result.passed} passed", style="green")
            if result.failed:
                summary.append(f"  {result.failed} failed", style="red")
            if result.errors:
                summary.append(f"  {result.errors} errors", style="red")

        if result.duration:
            summary.append(f"  ({result.duration})", style="dim")
        summary.append(f"  exit {result.returncode}", style="dim")

        self.write(summary)
