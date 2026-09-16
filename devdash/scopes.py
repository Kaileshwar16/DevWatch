"""Bounded package discovery; symlinks and generated trees are never followed."""
import os
from pathlib import Path

IGNORED = {'.git', 'node_modules', 'target', '.venv', 'venv', 'env', 'dist', 'build',
           '__pycache__', '.tox', '.cache', '.mypy_cache', '.pytest_cache', '.ruff_cache'}
MARKERS = {'package.json', 'pyproject.toml', 'requirements.txt', 'setup.cfg', 'Pipfile',
           'go.mod', 'go.work', 'Cargo.toml', 'Makefile', 'justfile', 'Taskfile.yml', 'Taskfile.yaml'}


def project_scopes(root: Path, warnings: list[str], *, max_depth=4, max_directories=512):
    pending = [(root, 0)]
    scopes = []
    visited = 0
    while pending and visited < max_directories:
        directory, depth = pending.pop(0)
        visited += 1
        try:
            with os.scandir(directory) as handle:
                entries = []
                for index, entry in enumerate(handle):
                    if index >= 10000:
                        warnings.append(f'{directory}: directory entry limit reached')
                        break
                    entries.append(entry)
            names = {entry.name for entry in entries}
            if directory == root or names & MARKERS:
                scopes.append(directory)
            # PostgreSQL storage is recognizable from metadata, without reading data.
            if {'PG_VERSION', 'base', 'global'} <= names:
                continue
            for entry in sorted(entries, key=lambda item: item.name):
                if entry.name in IGNORED or entry.name.startswith('.'):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if depth < max_depth:
                        pending.append((Path(entry.path), depth + 1))
        except OSError as exc:
            warnings.append(f'{directory}: {exc.strerror or type(exc).__name__}')
    if pending:
        warnings.append(f'Package discovery limited to {max_directories} directories (depth {max_depth})')
    return scopes
