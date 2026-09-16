"""Provider-neutral source identities and explicitly static graph evidence."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class SymbolLocation:
    path: str  # POSIX path relative to the selected project boundary
    line: int  # one-based; columns are zero-based AST byte offsets
    column: int = 0


@dataclass(frozen=True)
class SymbolRef:
    id: str
    name: str
    qualified_name: str
    kind: str
    location: SymbolLocation
    end_line: int


@dataclass(frozen=True)
class CallRelation:
    caller: SymbolRef
    expression: str
    callsite: SymbolLocation
    resolution: str  # resolved, ambiguous, unresolved
    callee: SymbolRef | None = None
    candidates: tuple[SymbolRef, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class EntryPoint:
    kind: str  # MAIN, TEST, CLI, HTTP, UNKNOWN
    label: str = ""


@dataclass
class TracePath:
    nodes: list[SymbolRef]  # entry -> requested symbol
    entry_kind: str = "UNKNOWN"
    entry_label: str = ""
    cycle: bool = False
    truncated: bool = False


@dataclass
class PathSearch:
    paths: list[TracePath] = field(default_factory=list)
    truncated: bool = False
    visited_nodes: int = 0


@dataclass
class TraceIndex:
    symbols: dict[str, SymbolRef] = field(default_factory=dict)
    relations: list[CallRelation] = field(default_factory=list)
    entries: dict[str, list[EntryPoint]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    truncated: bool = False
    files_indexed: int = 0
    files_parsed: int = 0
    index_ms: float = 0
    evidence: str = "static"


class TraceProvider(Protocol):
    """A provider produces an index; query/presentation code stays independent."""
    root: Path

    def refresh(self) -> TraceIndex: ...

    def preview(self, location: SymbolLocation, radius: int = 4) -> list[tuple[int, str]]: ...
