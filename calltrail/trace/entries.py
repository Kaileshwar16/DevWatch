"""Conservative entry-point labels using syntax and packaging data only."""
from pathlib import Path

from calltrail.metadata import read_toml
from calltrail.trace.models import EntryPoint, TraceIndex


def detect_entries(root: Path, index: TraceIndex, files, resolver):
    def add(symbol, kind, label=''):
        entries = index.entries.setdefault(symbol.id, [])
        entry = EntryPoint(kind, label)
        if entry not in entries:
            entries.append(entry)

    relations = iter(index.relations)
    for file in files:
        for call in file.calls:
            edge = next(relations)
            if call.main and edge.resolution == 'resolved':
                add(edge.callee, 'MAIN', 'Called in if __name__ == "__main__"')
        for scope in file.scopes.values():
            symbol = scope.symbol
            filename = Path(file.path).name
            if (symbol.kind in ('function', 'method') and symbol.name.startswith('test_')
                    and (filename.startswith('test_') or filename.endswith('_test.py'))):
                add(symbol, 'TEST', 'Conventional test name and source file')
            for parts, route in file.decorators.get(symbol.id, []):
                if (len(parts) == 2 and parts[0] in ('app', 'router')
                        and parts[1] in ('get', 'post', 'put', 'patch', 'delete', 'route', 'head', 'options')
                        and route.startswith('/')):
                    add(symbol, 'HTTP', f'{parts[1].upper()} {route} (decorator heuristic)')
    # Root packaging metadata only: project modules are never imported.
    manifest = root / 'pyproject.toml'
    if manifest.is_symlink():
        index.warnings.append('pyproject.toml: symlink packaging metadata ignored')
        return
    if manifest.is_file():
        try:
            scripts = read_toml(manifest).get('project', {}).get('scripts', {})
            if not isinstance(scripts, dict):
                raise ValueError('project.scripts must be a table')
            for name, value in scripts.items():
                if not isinstance(value, str) or ':' not in value:
                    continue
                module, target = value.split(':', 1)
                bindings = resolver.qualified(module + '.' + target, frozenset())
                if len(bindings) == 1:
                    binding = next(iter(bindings))
                    if binding.kind == 'symbol':
                        add(index.symbols[binding.target], 'CLI', f'project.scripts: {name}')
        except (OSError, ValueError, TypeError, AttributeError):
            index.warnings.append('pyproject.toml: CLI entry metadata could not be read')
