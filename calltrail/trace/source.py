"""Bounded, read-only source discovery independent of Git and execution tools."""
from __future__ import annotations

import io
import os
import stat
import tokenize
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from calltrail.scopes import IGNORED

EXCLUDED = IGNORED | {"site-packages", "generated", "vendor", "htmlcov", ".eggs"}


@dataclass(frozen=True)
class IndexLimits:
    max_files: int = 3000
    max_directories: int = 4000
    max_depth: int = 30
    max_entries: int = 100000
    max_file_bytes: int = 1024 * 1024
    max_total_bytes: int = 32 * 1024 * 1024
    max_ast_nodes: int = 100000
    max_symbols: int = 50000
    max_calls: int = 100000

    def __post_init__(self):
        if any(value <= 0 for value in vars(self).values()):
            raise ValueError("Index limits must be positive")


@dataclass
class SourceSet:
    files: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    truncated: bool = False


def source_files(root: Path, limits: IndexLimits) -> SourceSet:
    result = SourceSet()
    pending = deque([(root, 0)])
    directories = entries_seen = 0
    while pending:
        directory, depth = pending.popleft()
        directories += 1
        if directories > limits.max_directories:
            result.truncated = True
            break
        try:
            # Do not enter a nested repository or a linked worktree.
            if directory != root and (directory / ".git").exists():
                continue
            with os.scandir(directory) as handle:
                entries = []
                for entry in handle:
                    entries_seen += 1
                    if entries_seen > limits.max_entries:
                        result.truncated = True
                        break
                    entries.append(entry)
            if result.truncated:
                break
            for entry in sorted(entries, key=lambda item: item.name):
                if entry.name in EXCLUDED or entry.name.startswith('.') or entry.is_symlink():
                    continue
                path = Path(entry.path)
                if entry.is_dir(follow_symlinks=False):
                    if depth >= limits.max_depth:
                        result.truncated = True
                    else:
                        pending.append((path, depth + 1))
                elif entry.name.endswith('.py') and entry.is_file(follow_symlinks=False):
                    if len(result.files) >= limits.max_files:
                        result.truncated = True
                        pending.clear()
                        break
                    result.files.append(path)
        except OSError as exc:
            result.warnings.append(f"{directory.relative_to(root)}: {type(exc).__name__} during source discovery")
    if result.truncated:
        result.warnings.append("Source discovery truncated by index limits; relationships may be incomplete")
    return result


def read_source(root: Path, path: Path, max_bytes: int) -> tuple[str, tuple[int, ...]]:
    """Decode Python encoding cookies, bounded, without imports or symlink traversal."""
    relative = path.relative_to(root)
    if any(part in EXCLUDED or part.startswith('.') for part in relative.parts):
        raise ValueError("Excluded source path")
    if any((root.joinpath(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts) + 1)):
        raise ValueError("Symlink source paths are not indexed")
    if not path.resolve().is_relative_to(root):
        raise ValueError("Source path is outside the selected project")
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    with os.fdopen(os.open(path, flags), 'rb') as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
            raise ValueError("Source exceeds file size limit or is not a regular file")
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("Source exceeds file size limit")
    encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
    return data.decode(encoding), (info.st_mtime_ns, info.st_ctime_ns, info.st_size, info.st_ino)
