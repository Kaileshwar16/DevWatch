"""Explainable path rules and conservative, extensible check inference."""

from __future__ import annotations

import fnmatch
import os
import shlex
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from devdash.changes import ChangeSet, ChangedFile
from devdash.commands import Command


@dataclass
class ImpactReason:
    file: str
    strategy: str
    explanation: str
    pattern: str | None = None
    nearby_tests: list[str] = field(default_factory=list)


@dataclass
class AffectedCommand:
    name: str
    argv: list[str]
    cwd: str
    matched_files: list[str]
    matched_patterns: list[str]
    reasons: list[ImpactReason]
    preflight: dict | None = None
    provenance: str = ""


def matches_path(path: str, pattern: str) -> bool:
    """Case-sensitive, root-anchored globs; ** matches zero or more components."""
    parts, rules = path.split("/"), pattern.split("/")
    if ".." in parts:
        return False

    @lru_cache(maxsize=None)
    def match(i: int, j: int) -> bool:
        if j == len(rules):
            return i == len(parts)
        if rules[j] == "**":
            return match(i, j + 1) or (i < len(parts) and match(i + 1, j))
        return i < len(parts) and fnmatch.fnmatchcase(parts[i], rules[j]) and match(i + 1, j + 1)

    return match(0, 0)


def _nearby_python_tests(cwd: Path, relative: Path) -> list[Path]:
    """Probe a few conventional locations, never recursively walk the tree."""
    if relative.suffix != ".py":
        return []
    parts = relative.parts
    if parts[0] == "src":
        parts = parts[1:]
    module = Path(*parts)
    if parts[0] in ("tests", "test"):
        return [relative]  # Include deleted tests as evidence too.
    candidates = []
    for directory in ("tests", "test"):
        base = Path(directory)
        candidates.append(base / f"test_{module.stem}.py")
        if module.parent != Path("."):
            candidates.extend((base / module.parent, base / module.parent / f"test_{module.stem}.py"))
    return [path for path in candidates if (cwd / path).exists()]


def _infer(command: Command, path: str, root: Path, scopes: list[Path]) -> ImpactReason | None:
    # Automatically starting dev servers, formatters, or arbitrary scripts would
    # turn a check request into an unrelated operation. Explicit rules are opt-in.
    if command.name.split("@")[0].split(":")[0] not in ("test", "lint", "check", "typecheck", "type-check"):
        return None
    cwd = (command.cwd or root).resolve()
    absolute = Path(root / path)  # lexical: never follow a changed symlink
    absolute = Path(os.path.abspath(absolute))
    if absolute.is_relative_to(cwd):
        relative = absolute.relative_to(cwd)
        nearby = _nearby_python_tests(cwd, relative)
        if nearby and command.name.split("@")[0].split(":")[0] == "test":
            return ImpactReason(path, "python-nearby-tests",
                                "Nearby Python tests; retain the full suite for possible shared dependencies",
                                nearby_tests=[Path(os.path.relpath(cwd / p, root)).as_posix()
                                              for p in nearby])
        return ImpactReason(path, "working-directory", "Changed file is inside the check's working directory")
    # An unrelated sibling package has its own scoped checks. Root checks remain
    # selected above, while shared files outside known package scopes select all.
    if any(absolute.is_relative_to(scope) for scope in scopes if scope != root):
        return None
    return ImpactReason(path, "shared-file", "File outside package scopes may affect shared dependencies")


def affected_commands(root: Path, commands: dict[str, Command], files: list[ChangedFile]) -> list[AffectedCommand]:
    root = root.resolve()
    paths = list(dict.fromkeys(path for change in files for path in change.paths))
    scopes = [(command.cwd or root).resolve() for command in commands.values() if not command.service]
    results = []
    for command in commands.values():
        if command.service:
            continue
        reasons = []
        for path in paths:
            if command.paths is not None:
                reasons.extend(ImpactReason(path, "configured-path", "Matched configured path rule", pattern)
                               for pattern in dict.fromkeys(command.paths) if matches_path(path, pattern))
            elif command.source == "detected":
                reason = _infer(command, path, root, scopes)
                if reason:
                    reasons.append(reason)
        if reasons:
            results.append(AffectedCommand(
                command.name, command.argv.copy(), str(command.cwd or root),
                list(dict.fromkeys(reason.file for reason in reasons)),
                list(dict.fromkeys(reason.pattern for reason in reasons if reason.pattern)), reasons,
                command.preflight.public_dict() if command.preflight else None, command.provenance,
            ))
    # Prefer package-local checks before broad root checks, without dropping either.
    return sorted(results, key=lambda result: -len(Path(result.cwd).parts))


def impact_report(changes: ChangeSet, affected: list[AffectedCommand]) -> str:
    lines = ["Changed files"]
    for change in changes.files:
        path = f"{change.original_path} -> {change.path}" if change.original_path else change.path
        # repr protects the plain-text layout for names containing control characters.
        if any(ord(char) < 32 for char in path):
            path = repr(path)
        lines.append(f"  {change.status} {path}")
    if not changes.files:
        lines.append(f"  {changes.error or 'Working tree is clean.'}")
    if not affected:
        lines.extend(("", "No affected commands detected."))
        if changes.files:
            lines.append("No path rules or automatic check strategies matched these changes.")
    else:
        lines.extend(("", "Affected commands"))
        for result in affected:
            lines.extend((f"  {result.name}", f"    {shlex.join(result.argv)}"))
            if result.provenance:
                lines.append(f"    source: {result.provenance}")
            if result.preflight and not result.preflight["runnable"]:
                for error in result.preflight["errors"]:
                    lines.append(f"    {error['state'].upper()}: {error['summary']}")
            for reason in result.reasons:
                lines.append(f"    matched {reason.file}")
                lines.append(f"    rule: {reason.pattern}" if reason.pattern else f"    {reason.explanation}")
                if reason.nearby_tests:
                    lines.append("    nearby tests: " + ", ".join(reason.nearby_tests))
    return "\n".join(lines)
