"""Git information detection — orchestrates git CLI commands."""

from __future__ import annotations

from pathlib import Path

from devdash.changes import ChangeSet, collect_changes
from devdash.models import GitInfo
from devdash.runner import run_sync


def detect_git(root: Path, changes: ChangeSet | None = None) -> GitInfo | None:
    """Detect git info by running git commands. Returns None if not a repo."""
    changes = changes if changes is not None else collect_changes(root)
    if changes.repository_root is None:
        return None

    info = GitInfo()

    # Branch
    out, _, rc = run_sync(["git", "branch", "--show-current"], cwd=root)
    info.branch = out if rc == 0 else "detached"

    # If branch is empty, we might be in detached HEAD
    if not info.branch:
        out, _, rc = run_sync(["git", "rev-parse", "--short", "HEAD"], cwd=root)
        info.branch = f"({out})" if rc == 0 else "unknown"

    info.dirty = bool(changes.files)
    for change in changes.files:
        if change.untracked:
            info.untracked += 1
        elif "A" in change.status:
            info.added += 1
        elif "D" in change.status:
            info.deleted += 1
        else:
            info.modified += 1
        info.changed_files.append(change.path)

    # Ahead/behind upstream
    out, _, rc = run_sync(
        ["git", "rev-list", "--left-right", "--count", "HEAD...@{upstream}"],
        cwd=root,
    )
    if rc == 0 and out:
        parts = out.split()
        if len(parts) == 2:
            info.ahead = int(parts[0])
            info.behind = int(parts[1])

    # Last commit
    out, _, rc = run_sync(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=root,
    )
    if rc == 0:
        info.last_commit = out[:50]

    # Last commit time (relative)
    out, _, rc = run_sync(
        ["git", "log", "-1", "--pretty=%cr"],
        cwd=root,
    )
    if rc == 0:
        info.last_commit_time = out

    return info
