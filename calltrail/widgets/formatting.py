"""Shared borderless tables for terminal panels and detail views."""

from collections.abc import Iterable

from rich.table import Table
from rich.text import Text


def compact_table(headers: tuple[str, ...], rows: Iterable[Iterable[str | Text]]) -> Table:
    table = Table(box=None, padding=(0, 1), pad_edge=False, header_style="dim", highlight=False)
    for header in headers:
        table.add_column(header, overflow="fold")
    for row in rows:
        table.add_row(*(cell if isinstance(cell, Text) else Text(cell) for cell in row))
    return table
