"""Git information detection — orchestrates git CLI commands."""

from __future__ import annotations

from pathlib import Path

from devdash.models import GitInfo
from devdash.runner import run_sync


def detect_git(root: Path) -> GitInfo | None:
    """Detect git info by running git commands. Returns None if not a repo."""
    # Check if this is a git repo
    _, _, rc = run_sync(["git", "rev-parse", "--is-inside-work-tree"], cwd=root)
    if rc != 0:
        return None

    info = GitInfo()

    # Branch
    out, _, rc = run_sync(["git", "branch", "--show-current"], cwd=root)
    info.branch = out if rc == 0 else "detached"

    # If branch is empty, we might be in detached HEAD
    if not info.branch:
        out, _, rc = run_sync(["git", "rev-parse", "--short", "HEAD"], cwd=root)
        info.branch = f"({out})" if rc == 0 else "unknown"

    # Status (porcelain for machine parsing)
    out, _, rc = run_sync(["git", "status", "--porcelain=v1", "-z"], cwd=root)
    if rc == 0 and out:
        info.dirty = True
        records = iter(out.split("\0"))
        for line in records:
            if len(line) >= 2:
                index, work = line[0], line[1]
                if index == "?" or work == "?":
                    info.untracked += 1
                elif index == "A" or work == "A":
                    info.added += 1
                elif index == "D" or work == "D":
                    info.deleted += 1
                else:
                    info.modified += 1
                info.changed_files.append(line[3:])
                if index in "RC" or work in "RC":
                    next(records, None)  # Original path follows a rename/copy.

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
