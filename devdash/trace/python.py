"""Python AST provider: syntax and lexical bindings, never execution or imports."""
from __future__ import annotations

import ast
import threading
import time
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path

from devdash.trace.models import SymbolLocation, SymbolRef, TraceIndex
from devdash.trace.source import IndexLimits, read_source, source_files


@dataclass(frozen=True)
class Binding:
    kind: str  # symbol, import, module, receiver, unknown
    target: str = ""


@dataclass
class Scope:
    symbol: SymbolRef
    parent: str | None
    bindings: dict[str, list[Binding]] = field(default_factory=dict)
    rebound_attributes: set[tuple[str, ...]] = field(default_factory=set)

    def bind(self, name: str, value: Binding):
        values = self.bindings.setdefault(name, [])
        if value not in values:
            values.append(value)


@dataclass
class Call:
    owner: str
    parts: tuple[str, ...]
    expression: str
    location: SymbolLocation
    main: bool = False


@dataclass
class ParsedFile:
    path: str
    modules: tuple[str, ...]
    scopes: dict[str, Scope]
    calls: list[Call]
    decorators: dict[str, list[tuple[tuple[str, ...], str]]]


def dotted(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        prefix = dotted(node.value)
        return (*prefix, node.attr) if prefix else ()
    return ()


def module_names(path: str) -> tuple[str, ...]:
    parts = list(Path(path).with_suffix('').parts)
    if parts[-1] == '__init__':
        parts.pop()
    names = ['.'.join(parts)]
    if parts and parts[0] == 'src':
        names.append('.'.join(parts[1:]))
    return tuple(dict.fromkeys(names))


class FileIndexer(ast.NodeVisitor):
    def __init__(self, path: str, tree: ast.Module):
        module = SymbolRef(f'{path}:module', '<module>', '<module>', 'module',
                           SymbolLocation(path, 1), max((getattr(n, 'end_lineno', 1) or 1 for n in tree.body), default=1))
        self.file = ParsedFile(path, module_names(path), {module.id: Scope(module, None)}, [], {})
        self.current = module.id
        self.main = False

    @property
    def scope(self):
        return self.file.scopes[self.current]

    def location(self, node):
        return SymbolLocation(self.file.path, node.lineno, node.col_offset)

    def definition(self, node, kind):
        parent = self.scope.symbol
        qualified = node.name if parent.kind == 'module' else f'{parent.qualified_name}.{node.name}'
        symbol = SymbolRef(f'{self.file.path}:{node.lineno}:{qualified}', node.name, qualified, kind,
                           self.location(node), node.end_lineno or node.lineno)
        self.scope.bind(node.name, Binding('symbol', symbol.id))
        self.file.scopes[symbol.id] = Scope(symbol, self.current)
        decorators = []
        for decorator in node.decorator_list:
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            label = ''
            if isinstance(decorator, ast.Call) and decorator.args and isinstance(decorator.args[0], ast.Constant):
                if isinstance(decorator.args[0].value, str):
                    label = decorator.args[0].value[:200]
            decorators.append((dotted(target), label))
        self.file.decorators[symbol.id] = decorators
        old, old_main = self.current, self.main
        self.current, self.main = symbol.id, False
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            positional = [*node.args.posonlyargs, *node.args.args]
            args = [*positional, *node.args.kwonlyargs]
            args += [arg for arg in (node.args.vararg, node.args.kwarg) if arg]
            static = any(parts and parts[-1] == 'staticmethod' for parts, _ in decorators)
            for arg in args:
                receiver = parent.kind == 'class' and positional and arg is positional[0] and not static
                binding = Binding('receiver', parent.id) if receiver else Binding('unknown')
                self.scope.bind(arg.arg, binding)
        for statement in node.body:
            self.visit(statement)
        self.current, self.main = old, old_main

    def visit_FunctionDef(self, node):
        self.definition(node, 'method' if self.scope.symbol.kind == 'class' else 'function')

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self.definition(node, 'class')

    def visit_Import(self, node):
        for alias in node.names:
            self.scope.bind(alias.asname or alias.name.split('.')[0],
                            Binding('module', alias.name if alias.asname else alias.name.split('.')[0]))

    def visit_ImportFrom(self, node):
        if any(alias.name == '*' for alias in node.names):
            self.scope.bind('*', Binding('unknown'))
        for alias in node.names:
            # Relative import strings are expanded by the resolver for each module alias.
            target = '.' * node.level + (node.module or '')
            self.scope.bind(alias.asname or alias.name, Binding('import', target + ':' + alias.name))

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.scope.bind(node.id, Binding('unknown'))

    def visit_Attribute(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.scope.rebound_attributes.add(dotted(node))
        self.generic_visit(node)

    def visit_MatchAs(self, node):
        if node.name:
            self.scope.bind(node.name, Binding('unknown'))
        self.generic_visit(node)

    visit_MatchStar = visit_MatchAs

    def visit_MatchMapping(self, node):
        if node.rest:
            self.scope.bind(node.rest, Binding('unknown'))
        self.generic_visit(node)

    def visit_Global(self, node):
        for name in node.names:
            self.scope.bind(name, Binding('unknown'))

    visit_Nonlocal = visit_Global

    def visit_ExceptHandler(self, node):
        if node.name:
            self.scope.bind(node.name, Binding('unknown'))
        self.generic_visit(node)

    def visit_Lambda(self, node):
        # A callback body is not a direct call of its defining function.
        pass

    def visit_ListComp(self, node):
        # Comprehensions introduce a scope; don't confuse their locals with globals.
        self.file.calls.append(Call(self.current, (), '<comprehension>', self.location(node), self.main))

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp

    def visit_Call(self, node):
        parts = dotted(node.func)
        expression = '.'.join(parts) + '()' if parts else '<dynamic call>()'
        self.file.calls.append(Call(self.current, parts, expression, self.location(node), self.main))
        self.generic_visit(node)

    def visit_If(self, node):
        test = node.test
        guard = (self.scope.symbol.kind == 'module' and isinstance(test, ast.Compare)
                 and len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq)
                 and isinstance(test.left, ast.Name) and test.left.id == '__name__'
                 and len(test.comparators) == 1 and isinstance(test.comparators[0], ast.Constant)
                 and test.comparators[0].value == '__main__')
        self.visit(test)
        previous = self.main
        self.main = self.main or guard
        for statement in node.body:
            self.visit(statement)
        self.main = previous
        for statement in node.orelse:
            self.visit(statement)


class PythonAstProvider:
    """One session cache; changed files reparse and all cross-file edges re-resolve."""
    def __init__(self, root: Path, limits: IndexLimits | None = None):
        self.root = root.resolve()
        if not self.root.is_dir():
            raise ValueError('Trace root must be a directory')
        if self.root == self.root.parent:
            raise ValueError('Select a project directory rather than a filesystem root')
        self.limits = limits or IndexLimits()
        self._cache: dict[str, tuple[tuple[int, ...], ParsedFile | None, str]] = {}
        self._lock = threading.Lock()

    def refresh(self) -> TraceIndex:
        with self._lock:
            return self._refresh()

    def _refresh(self) -> TraceIndex:
        started = time.perf_counter()
        sources = source_files(self.root, self.limits)
        index = TraceIndex(warnings=sources.warnings, truncated=sources.truncated)
        files = []
        active = set()
        total = symbols = calls = 0
        for path in sources.files:
            relative = path.relative_to(self.root).as_posix()
            active.add(relative)
            try:
                info = path.stat()
                total += info.st_size
                if total > self.limits.max_total_bytes:
                    index.truncated = True
                    index.warnings.append('Total source byte limit reached')
                    break
                signature = (info.st_mtime_ns, info.st_ctime_ns, info.st_size, info.st_ino)
                cached = self._cache.get(relative)
                if cached and cached[0] == signature:
                    parsed, warning = cached[1:]
                else:
                    parsed, warning = None, ''
                    index.files_parsed += 1
                    try:
                        text, signature = read_source(self.root, path, self.limits.max_file_bytes)
                        tree = ast.parse(text, filename=relative)
                        if sum(1 for _ in islice(ast.walk(tree), self.limits.max_ast_nodes + 1)) > self.limits.max_ast_nodes:
                            raise ValueError('AST node limit exceeded')
                        visitor = FileIndexer(relative, tree)
                        visitor.visit(tree)
                        parsed = visitor.file
                    except (OSError, ValueError, SyntaxError, UnicodeError, RecursionError) as exc:
                        warning = f'{relative}: {type(exc).__name__}; source could not be indexed'
                    self._cache[relative] = signature, parsed, warning
                if warning:
                    index.warnings.append(warning)
                if parsed:
                    symbols += len(parsed.scopes)
                    calls += len(parsed.calls)
                    if symbols > self.limits.max_symbols or calls > self.limits.max_calls:
                        index.truncated = True
                        index.warnings.append('Symbol/call index limit reached')
                        break
                    files.append(parsed)
            except OSError as exc:
                index.warnings.append(f'{relative}: {type(exc).__name__}; source unavailable')
        self._cache = {name: item for name, item in self._cache.items() if name in active}
        index.files_indexed = len(files)
        index.symbols = {key: scope.symbol for file in files for key, scope in file.scopes.items()}
        # Later stages populate relations and entries without changing the index API.
        self._link(index, files)
        index.index_ms = (time.perf_counter() - started) * 1000
        return index

    def _link(self, index: TraceIndex, files: list[ParsedFile]):
        from devdash.trace.entries import detect_entries
        from devdash.trace.resolution import Resolver
        resolver = Resolver(files)
        resolver.populate(index, files)
        detect_entries(self.root, index, files, resolver)

    def preview(self, location: SymbolLocation, radius: int = 4) -> list[tuple[int, str]]:
        path = self.root / location.path
        if path.suffix != '.py':
            raise ValueError('Trace unavailable for this language in this version')
        text, _ = read_source(self.root, path, self.limits.max_file_bytes)
        radius = min(max(radius, 0), 10)
        start = max(1, location.line - radius)
        return [(i, line[:240]) for i, line in enumerate(text.splitlines(), 1)
                if start <= i <= location.line + radius]
