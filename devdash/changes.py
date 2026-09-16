"""One machine-readable Git change snapshot, including both sides of renames."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from devdash.runner import run_sync


@dataclass
class ChangedFile:
    path: str
    index_status: str = " "
    worktree_status: str = " "
    original_path: str | None = None

    @property
    def staged(self) -> bool:
        return self.index_status not in (" ", "?")

    @property
    def unstaged(self) -> bool:
        return self.worktree_status not in (" ", "?")

    @property
    def untracked(self) -> bool:
        return self.index_status == "?"

    @property
    def status(self) -> str:
        return (self.index_status + self.worktree_status).strip()

    @property
    def paths(self) -> list[str]:
        return [self.path] + ([self.original_path] if self.original_path else [])


@dataclass
class ChangeSet:
    files: list[ChangedFile] = field(default_factory=list)
    repository_root: Path | None = None
    error: str = ""


def collect_changes(root: Path) -> ChangeSet:
    """Paths are relative to the selected project, which may be inside a worktree.

    Keep outside paths (../) too: changes to shared repository configuration can
    affect a package. Git's NUL protocol preserves whitespace and rename pairs.
    """
    root = root.resolve()
    out, err, code = run_sync(["git", "rev-parse", "--show-toplevel"], root, nul_output=True)
    if code:
        return ChangeSet(error=f"Git changes unavailable: {err.strip() or 'not a working tree'}")
    # rev-parse adds exactly one newline; directory names may themselves contain one.
    repository = Path(out.removesuffix("\n")).resolve()
    out, err, code = run_sync(
        ["git", "--no-optional-locks", "-c", "status.relativePaths=false", "status",
         "--porcelain=v1", "-z", "--untracked-files=all", "--renames", "--ignore-submodules=none"],
        repository, nul_output=True,
    )
    if code:
        return ChangeSet(repository_root=repository, error=f"Git changes unavailable: {err.strip()}")

    def relative(path: str) -> str:
        # Do not resolve individual paths: deleted paths and symlinks are valid changes.
        return Path(os.path.relpath(repository / path, root)).as_posix()

    files = []
    records = iter(out.split("\0"))
    for record in records:
        if not record:
            continue
        index, work = record[:2]
        original = next(records) if index in "RC" or work in "RC" else None
        files.append(ChangedFile(relative(record[3:]), index, work,
                                 relative(original) if original else None))
    return ChangeSet(files, repository)
