"""Conservative static command metadata; no recipe bodies or CI expressions execute."""
import re
import shlex
from pathlib import Path
from calltrail.metadata import read_text, read_toml

CHECKS = ('test', 'lint', 'check', 'typecheck', 'type-check')


def canonical_commands(root: Path, warnings: list[str]):
    """Yield (name, argv, provenance). Ambiguous YAML/recipes are left to config."""
    for filename, runner in (('Makefile', 'make'), ('justfile', 'just'),
                             ('Taskfile.yml', 'task'), ('Taskfile.yaml', 'task')):
        path = root / filename
        if not path.is_file():
            continue
        try:
            content = read_text(path)
            if runner == 'task':
                # Only the conventional top-level tasks map and plain task keys.
                in_tasks = False
                for line in content.splitlines():
                    if line == 'tasks:':
                        in_tasks = True
                    elif line and not line.startswith((' ', '#')):
                        in_tasks = False
                    if in_tasks:
                        match = re.fullmatch(r'  ([\w-]+):\s*(?:#.*)?', line)
                        if match and match[1] in CHECKS:
                            yield match[1], [runner, match[1]], filename
            else:
                for line in content.splitlines():
                    match = re.match(r'^([A-Za-z][\w-]*):(?:[^=]|$)', line)
                    if match and match[1] in CHECKS:
                        yield match[1], [runner, match[1]], filename
        except (OSError, ValueError) as exc:
            warnings.append(f'{path}: {exc}')
    # PDM's simple cmd form has direct argument semantics; Python entry points do not.
    path = root / 'pyproject.toml'
    if path.is_file():
        try:
            scripts = read_toml(path).get('tool', {}).get('pdm', {}).get('scripts', {})
            for name, value in scripts.items():
                if name in CHECKS and (isinstance(value, str) or isinstance(value, dict) and 'cmd' in value):
                    yield name, ['pdm', 'run', name], 'pyproject.toml'
        except (OSError, ValueError, AttributeError, TypeError) as exc:
            warnings.append(f'{path}: {exc}')
    workflows = root / '.github' / 'workflows'
    if not workflows.is_dir():
        return
    for path in sorted(workflows.iterdir())[:50]:
        if path.suffix not in ('.yml', '.yaml') or not path.is_file():
            continue
        try:
            content = read_text(path)
            # A changed working directory or environment can alter semantics. Reject
            # the whole workflow rather than guess at YAML job/default inheritance.
            if any(marker in content for marker in ('working-directory:', 'defaults:', 'env:', 'container:')):
                continue
            for line in content.splitlines():
                match = re.fullmatch(r'\s*(?:-\s*)?run:\s+(.+)', line)
                if not match:
                    continue
                value = match[1]
                if any(char in value for char in '|>&;$`{}#'):
                    continue
                argv = shlex.split(value)
                # Recognize only direct check invocations, never arbitrary CI code.
                if len(argv) >= 2 and argv[:2] in (['go', 'test'], ['cargo', 'test'], ['ruff', 'check']):
                    name = 'lint' if argv[0] == 'ruff' else 'test'
                elif argv and argv[0] == 'pytest':
                    name = 'test'
                else:
                    continue
                yield name, argv, path.relative_to(root).as_posix()
        except (OSError, ValueError) as exc:
            warnings.append(f'{path}: {exc}')
