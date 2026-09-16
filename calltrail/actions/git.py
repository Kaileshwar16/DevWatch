"""Git actions — quick git operations."""

from __future__ import annotations

from pathlib import Path

from calltrail.runner import run_async


async def git_pull(cwd: Path) -> tuple[str, int]:
    """Run git pull."""
    out, err, rc = await run_async(["git", "pull"], cwd=cwd, timeout=30.0)
    return out or err, rc


async def git_push(cwd: Path) -> tuple[str, int]:
    """Run git push."""
    out, err, rc = await run_async(["git", "push"], cwd=cwd, timeout=30.0)
    return out or err, rc


async def git_status(cwd: Path) -> tuple[str, int]:
    """Run git status."""
    out, err, rc = await run_async(["git", "status"], cwd=cwd, timeout=10.0)
    return out or err, rc


async def git_diff_stat(cwd: Path) -> tuple[str, int]:
    """Show both staged and unstaged changes, including unborn branches."""
    sections = []
    code = 0
    for label, args in (("Unstaged", []), ("Staged", ["--cached"])):
        out, err, rc = await run_async(["git", "--no-pager", "diff", *args, "--stat", "--no-ext-diff"], cwd=cwd)
        sections.append(f"{label}:\n{out or err or '(none)'}")
        code = code or rc
    return "\n\n".join(sections), code


async def git_log_short(cwd: Path, count: int = 10) -> tuple[str, int]:
    """Run git log --oneline."""
    out, err, rc = await run_async(
        ["git", "log", f"-{count}", "--oneline", "--decorate"],
        cwd=cwd, timeout=10.0,
    )
    return out or err, rc
