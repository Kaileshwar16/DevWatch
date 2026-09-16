"""Provider-independent lookup, adjacency queries and bounded reverse paths."""
from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path

from calltrail.trace.models import EntryPoint, PathSearch, SymbolRef, TraceIndex, TracePath


class CallHierarchy:
    def __init__(self, root: Path, index: TraceIndex):
        self.root = root.resolve()
        self.index = index
        self._incoming = defaultdict(list)
        self._outgoing = defaultdict(list)
        self._names = defaultdict(list)
        self._files = defaultdict(list)
        for symbol in index.symbols.values():
            self._files[symbol.location.path].append(symbol)
            if symbol.kind != 'module':
                for name in {symbol.name, symbol.qualified_name}:
                    self._names[name].append(symbol)
        for relation in index.relations:
            self._outgoing[relation.caller.id].append(relation)
            if relation.callee:
                self._incoming[relation.callee.id].append(relation)
            for candidate in relation.candidates:
                self._incoming[candidate.id].append(relation)

    def lookup(self, target: str) -> list[SymbolRef]:
        """Ambiguous names return candidates; file:line selects the innermost scope."""
        path, separator, line = target.rpartition(':')
        if separator and line.isdigit():
            if int(line) < 1:
                raise ValueError('Source line must be positive')
            file = self.root / path
            if file.suffix != '.py':
                raise ValueError('Trace unavailable for this language in this version; only Python is supported')
            if not file.resolve().is_relative_to(self.root):
                raise ValueError('Trace target is outside the selected project')
            relative = file.resolve().relative_to(self.root).as_posix()
            symbols = [s for s in self._files.get(relative, [])
                       if s.location.line <= int(line) <= s.end_line and s.kind != 'module']
            if not symbols:
                return []
            # Nested scopes overlap intentionally. The narrowest enclosing scope wins.
            span = min(s.end_line - s.location.line for s in symbols)
            return sorted((s for s in symbols if s.end_line - s.location.line == span), key=lambda s: s.id)
        if Path(target).suffix and ('/' in target or Path(target).suffix in ('.py', '.js', '.ts', '.go', '.rs', '.cpp')):
            if Path(target).suffix != '.py':
                raise ValueError('Trace unavailable for this language in this version; only Python is supported')
            raise ValueError('Specify a Python source location as file.py:line')
        return sorted(self._names.get(target, []), key=lambda s: s.id)

    def incoming(self, symbol: SymbolRef):
        return self._incoming.get(symbol.id, [])

    def outgoing(self, symbol: SymbolRef):
        return self._outgoing.get(symbol.id, [])

    def to_entry(self, symbol: SymbolRef, *, max_depth: int = 12, max_paths: int = 30,
                 max_nodes: int = 2000) -> PathSearch:
        if not 1 <= max_depth <= 100 or not 1 <= max_paths <= 1000 or not 1 <= max_nodes <= 100000:
            raise ValueError('Path limits: depth 1–100, paths 1–1000, nodes 1–100000')
        result = PathSearch()
        queue = deque([(symbol, [symbol], frozenset({symbol.id}))])
        scheduled = 1
        while queue and result.visited_nodes < max_nodes and len(result.paths) < max_paths:
            current, reverse, seen = queue.popleft()
            result.visited_nodes += 1
            entries = self.index.entries.get(current.id, [])
            callers = {edge.caller.id: edge.caller for edge in self.incoming(current)
                       if edge.resolution == 'resolved'}
            depth_limit = len(reverse) - 1 >= max_depth
            if entries or not callers or depth_limit:
                for entry in entries or [EntryPoint('UNKNOWN', 'No resolved project caller')]:
                    if len(result.paths) >= max_paths:
                        result.truncated = True
                        break
                    result.paths.append(TracePath(list(reversed(reverse)), entry.kind, entry.label,
                                                  truncated=depth_limit and bool(callers) and not entries))
                result.truncated |= depth_limit and bool(callers) and not entries
                continue
            ordered = sorted(callers.values(), key=lambda s: (s.id not in self.index.entries, s.id))
            for caller in ordered:
                if caller.id in seen:
                    if len(result.paths) < max_paths:
                        result.paths.append(TracePath(list(reversed([*reverse, caller])), cycle=True))
                    else:
                        result.truncated = True
                elif scheduled < max_nodes:
                    queue.append((caller, [*reverse, caller], seen | {caller.id}))
                    scheduled += 1
                else:
                    result.truncated = True
        result.truncated |= bool(queue)
        result.paths.sort(key=lambda path: (len(path.nodes), path.entry_kind == 'UNKNOWN',
                                           tuple(s.id for s in path.nodes)))
        return result
