"""Check task prerequisites without running project commands."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from devdash.commands import Command
from devdash.preflight import preflight_command


@dataclass
class Check:
    name: str
    ok: bool
    message: str


def check_commands(root: Path, commands: dict[str, Command]) -> list[Check]:
    checks = []
    for name, command in commands.items():
        result = preflight_command(command, root)
        command.preflight = result
        message = result.executable or ''
        if result.errors:
            message = '; '.join(issue.summary + ('\n' + issue.detail if issue.detail else '') for issue in result.errors)
        checks.append(Check(name, result.runnable, message))
    return checks


async def doctor_report(root, config, commands, *, debug=False):
    import asyncio
    import os
    import shutil
    from devdash.discovery import collect_project
    from devdash.diagnostics import diagnostic_report
    checks, info = await asyncio.gather(asyncio.to_thread(check_commands, root, commands),
                                        collect_project(root, config, commands))
    readable = os.access(root, os.R_OK | os.X_OK)
    lines = ['DevWatch doctor', f'Project: {root}', 'Configuration: valid',
             f'{"OK" if readable else "ERROR"} project root readable',
             f'{"OK Git repository" if info.git else "INFO Not a Git repository"}', 'Tools:']
    tools = {'git', 'docker'} | {command.argv[0] for command in commands.values() if command.argv}
    for tool in sorted(tools):
        lines.append(f'  {"OK" if shutil.which(tool) else "INFO unavailable"} {tool}')
    lines.append('Commands:')
    for check in checks:
        command = commands[check.name]
        preflight = command.preflight
        state = 'OK' if check.ok else preflight.errors[0].state.value.upper()
        import shlex
        lines.extend((f'  {state} {check.name}', f'    command: {shlex.join(command.argv)}',
                      f'    source: {command.provenance}', f'    cwd: {command.cwd}', f'    {check.message}'))
        lines.extend(f'    warning: {warning}' for warning in preflight.warnings)
    if not checks:
        lines.append('  No commands detected. Run devdash --init to configure tasks.')
    docker_problem = bool(info.docker and info.docker.compose_file and (not info.docker.available or info.docker.error))
    lines.append('Docker: ' + ('OK daemon reachable' if info.docker and info.docker.available else
                               'ERROR daemon unavailable' if docker_problem else 'INFO optional daemon unavailable'))
    warnings = getattr(commands, 'warnings', [])
    lines.extend(f'Warning: {warning}' for warning in warnings)
    failures = sum(not check.ok for check in checks)
    lines.append(f'Problems: {failures} command(s); {len(warnings)} discovery warning(s)')
    lines.append('Read-only checks; dependencies are never installed and project scripts are never executed.')
    if debug:
        lines.extend(('', diagnostic_report(info, commands)))
    # Missing optional Git/Docker tools preserve previous doctor success semantics.
    unhealthy = failures or warnings or not readable or docker_problem or any(not item.ok for item in info.diagnostics)
    return '\n'.join(lines), 1 if unhealthy else 0
