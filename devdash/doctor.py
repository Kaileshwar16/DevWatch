"""Check task prerequisites without running project commands."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from devdash.commands import Command
from devdash.runner import project_environment


@dataclass
class Check:
    name: str
    ok: bool
    message: str


def check_commands(root: Path, commands: dict[str, Command]) -> list[Check]:
    checks = []
    for name, command in commands.items():
        cwd = command.cwd or root
        if not cwd.is_dir():
            checks.append(Check(name, False, f"Working directory does not exist: {cwd}"))
            continue
        executable = command.argv[0]
        env = {**project_environment(cwd), **command.env}
        if os.path.dirname(executable):
            candidate = cwd / executable
            found = str(candidate) if candidate.is_file() and os.access(candidate, os.X_OK) else None
        else:
            # Relative PATH entries are relative to the task's working directory.
            search = os.pathsep.join(str(cwd / entry) for entry in env.get("PATH", os.defpath).split(os.pathsep))
            found = shutil.which(executable, path=search)
        checks.append(Check(name, bool(found), found or f"Executable not found or not executable: {executable}"))
    return checks
