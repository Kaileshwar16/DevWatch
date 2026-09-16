"""Read-only command prerequisites. Never import project modules or run scripts."""
from __future__ import annotations

import os
import shlex
import shutil
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from devdash.outcomes import ExecutionReason as Reason, ExecutionResult, ExecutionState as State
from devdash.runner import project_environment

if TYPE_CHECKING:
    from devdash.commands import Command


@dataclass
class PreflightIssue:
    reason: Reason
    summary: str
    detail: str = ""
    state: State = State.UNAVAILABLE
    suggestion: str = ""


@dataclass
class CommandPreflight:
    runnable: bool
    executable: str | None
    cwd: str
    warnings: list[str] = field(default_factory=list)
    errors: list[PreflightIssue] = field(default_factory=list)

    @property
    def reason(self) -> Reason | None:
        return self.errors[0].reason if self.errors else None

    def public_dict(self) -> dict:
        return {**asdict(self), "reason": self.reason}

    def result(self) -> ExecutionResult:
        issue = self.errors[0]
        code = 127 if issue.state == State.UNAVAILABLE else 126
        return ExecutionResult(issue.state, code, issue.reason, issue.summary, issue.detail,
                               suggestion=issue.suggestion)


def resolve_executable(executable: str, cwd: Path, env: dict[str, str]) -> str | None:
    if os.path.dirname(executable):
        candidate = cwd / executable
        return str(candidate) if candidate.is_file() and os.access(candidate, os.X_OK) else None
    search = os.pathsep.join(str(cwd / entry) for entry in env.get("PATH", os.defpath).split(os.pathsep))
    return shutil.which(executable, path=search)


def go_discovery_hazards(root: Path, limit: int = 10000) -> tuple[list[str], bool]:
    """Bounded Go-like walk. Never apply DevDash's generated-directory exclusions.

    Go ignores dot/underscore directories, testdata, vendor and nested modules.
    Permission failures elsewhere must remain visible even for runtime data.
    """
    pending = [root]
    errors = []
    visited = 0
    while pending and visited < limit:
        directory = pending.pop()
        visited += 1
        try:
            with os.scandir(directory) as entries:
                for index, entry in enumerate(entries):
                    if index >= limit:
                        return errors, False
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name.startswith(('.', '_')) or entry.name in ('testdata', 'vendor'):
                            continue
                        child = Path(entry.path)
                        try:
                            if (child / 'go.mod').is_file():
                                continue
                        except PermissionError:
                            errors.append(f"{child.relative_to(root)}: permission denied")
                            continue
                        pending.append(child)
        except PermissionError:
            errors.append(f"{directory.relative_to(root)}: permission denied")
        except OSError as exc:
            errors.append(f"{directory.relative_to(root)}: {exc.strerror}")
    return errors, not pending


def _node_prerequisite(command: Command, cwd: Path, env: dict[str, str], result: CommandPreflight) -> None:
    from devdash.metadata import read_json
    argv = command.argv
    if len(argv) < 2 or argv[0] not in ('npm', 'pnpm', 'yarn', 'bun'):
        return
    script_name = argv[2] if len(argv) >= 3 and argv[1] == 'run' else argv[1]
    if script_name.startswith('-'):
        return
    package = read_json(cwd / 'package.json')
    script = package.get('scripts', {}).get(script_name) if isinstance(package.get('scripts', {}), dict) else None
    if not isinstance(script, str):
        return
    try:
        tokens = shlex.split(script)
    except ValueError:
        result.errors.append(PreflightIssue(Reason.CONFIGURATION_ERROR, 'Invalid package script quoting',
                                            state=State.ERROR))
        return
    # Only a simple leading executable. Shell compositions/wrappers are uncertain.
    if not tokens or any(char in script for char in '|&;$`\n<>') or '=' in tokens[0]:
        result.warnings.append('Complex package script: dependency resolution deferred to the package manager')
        return
    executable = tokens[0]
    if executable not in ('jest', 'vitest', 'eslint', 'tsc', 'mocha', 'ava', 'vite', 'next', 'tsx', 'nyc'):
        return
    for directory in (cwd, *cwd.parents):
        binary = directory / 'node_modules' / '.bin' / executable
        if (binary.is_file() and os.access(binary, os.X_OK)) or binary.with_suffix('.cmd').is_file():
            return
        if (directory / '.pnp.cjs').is_file() or (directory / '.pnp.js').is_file():
            result.warnings.append('Yarn Plug’n’Play dependency resolution deferred to Yarn')
            return
    if resolve_executable(executable, cwd, env):
        return
    result.errors.append(PreflightIssue(
        Reason.DEPENDENCY_MISSING, f'{executable} could not be resolved in the project environment',
        f'package.json defines {script_name}, but its executable is unavailable',
        suggestion=f"Install the project's dependencies using its configured package manager ({argv[0]})."))


def _python_prerequisite(command: Command, cwd: Path, executable: str, result: CommandPreflight) -> None:
    argv = command.argv
    if argv[0] not in ('uv', 'poetry', 'pdm', 'pipenv') and not Path(executable).name.startswith('python'):
        return
    runner = argv[0]
    managed = runner in ('uv', 'poetry', 'pdm', 'pipenv')
    if managed:
        venv = next((cwd / name for name in ('.venv', 'venv', 'env')
                     if (cwd / name / 'pyvenv.cfg').is_file()), None)
        if venv is None:
            result.errors.append(PreflightIssue(
                Reason.DEPENDENCY_MISSING, f'{runner} project environment is not available locally',
                'No .venv, venv or env with pyvenv.cfg found; external manager environments are not probed.',
                suggestion='Prepare the project environment yourself, or configure its explicit interpreter.'))
            return
    else:
        # Resolve PATH, but preserve the interpreter symlink path identifying a venv.
        candidate = Path(executable).absolute().parent.parent
        venv = candidate if (candidate / 'pyvenv.cfg').is_file() else None
    if '-m' not in argv:
        return
    index = argv.index('-m')
    if index + 1 >= len(argv) or argv[index + 1] != 'pytest':
        return
    if venv:
        sites = list((venv / 'lib').glob('python*/site-packages')) + [venv / 'Lib' / 'site-packages']
    elif Path(executable).resolve() == Path(sys.executable).resolve():
        sites = [Path(p) for p in sys.path if p and ('site-packages' in p or 'dist-packages' in p)]
    else:
        result.warnings.append('pytest availability in the selected interpreter is verified at execution time')
        return
    if not any((site / 'pytest' / '__main__.py').is_file() for site in sites):
        result.errors.append(PreflightIssue(Reason.DEPENDENCY_MISSING, 'pytest cannot be resolved in the selected environment',
                                            suggestion="Install the project's test dependencies in its intended environment."))


def preflight_command(command: Command, root: Path, *, thorough: bool = True) -> CommandPreflight:
    cwd = command.cwd or root
    result = CommandPreflight(True, None, str(cwd))
    try:
        from devdash.config import command_args
        if not isinstance(command.argv, list):
            raise ValueError("Command argv must be an argument array")
        command_args(command.argv)
        if not cwd.is_dir():
            result.errors.append(PreflightIssue(Reason.INVALID_WORKING_DIRECTORY,
                                                f'Working directory does not exist: {cwd}'))
        elif not os.access(cwd, os.R_OK | os.X_OK):
            result.errors.append(PreflightIssue(Reason.PERMISSION_DENIED, 'Working directory is not readable',
                                                str(cwd), State.ERROR))
        else:
            env = {**project_environment(cwd), **command.env}
            result.executable = resolve_executable(command.argv[0], cwd, env)
            if not result.executable:
                result.errors.append(PreflightIssue(Reason.COMMAND_NOT_FOUND,
                    f'Executable not found or not executable: {command.argv[0]}'))
            else:
                _node_prerequisite(command, cwd, env, result)
                _python_prerequisite(command, cwd, result.executable, result)
            if not thorough and command.argv[:2] == ["go", "test"] and "./..." in command.argv:
                result.warnings.append("Recursive Go package discovery is checked by --doctor and before execution")
            if thorough and command.argv[:2] == ['go', 'test'] and './...' in command.argv:
                hazards, complete = go_discovery_hazards(cwd)
                if hazards:
                    result.errors.insert(0, PreflightIssue(Reason.DISCOVERY_FAILED, 'Go package discovery failed',
                        'go test ./... cannot enumerate packages:\n' + '\n'.join(hazards), State.ERROR,
                        'Use a project-defined test target or configure an explicit package scope.'))
                if not complete:
                    result.warnings.append('Go filesystem preflight reached its scan limit; discovery may still fail')
    except (ValueError, TypeError) as exc:
        result.errors.append(PreflightIssue(Reason.CONFIGURATION_ERROR, 'Invalid command', str(exc), State.ERROR))
    except OSError as exc:
        result.errors.append(PreflightIssue(Reason.PERMISSION_DENIED, 'Cannot inspect command prerequisites',
                                            str(exc), State.ERROR))
    result.runnable = not result.errors
    return result
