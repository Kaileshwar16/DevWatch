"""Shared dashboard and CLI snapshot collection with independent detector failures."""
from __future__ import annotations
import asyncio
import time
from pathlib import Path
from calltrail.changes import ChangeSet, collect_changes
from calltrail.commands import Command, discover_commands
from calltrail.config import CallTrailConfig
from calltrail.detectors.docker import detect_docker
from calltrail.detectors.git import detect_git
from calltrail.detectors.language import detect_frameworks, detect_languages, detect_package_manager
from calltrail.detectors.ports import detect_ports
from calltrail.detectors.project import detect_env_files, detect_project_name, detect_venv
from calltrail.detectors.runtime import detect_runtime
from calltrail.diagnostics import Diagnostic
from calltrail.models import ProjectInfo
from calltrail.impact import affected_commands


async def collect_project(root: Path, config: CallTrailConfig,
                          commands: dict[str, Command] | None = None) -> ProjectInfo:
    info = ProjectInfo(root=root)

    async def probe(name, fn, args, fallback):
        started = time.perf_counter()
        try:
            value = await asyncio.to_thread(fn, *args)
        except Exception as exc:
            # Exception messages can contain arbitrary manifest data or credentials.
            info.warnings.append(f'{name}: {type(exc).__name__} during detection')
            info.diagnostics.append(Diagnostic(name, (time.perf_counter()-started)*1000, False, type(exc).__name__))
            return fallback
        info.diagnostics.append(Diagnostic(name, (time.perf_counter()-started)*1000))
        return value

    metadata = {
        'name': (detect_project_name, root.name), 'languages': (detect_languages, []),
        'frameworks': (detect_frameworks, []), 'package_manager': (detect_package_manager, None),
        'venv': (detect_venv, None), 'has_env': (detect_env_files, False),
    }
    values = await asyncio.gather(*(probe(name, fn, (root,), fallback) for name, (fn, fallback) in metadata.items()))
    for name, value in zip(metadata, values):
        setattr(info, name, value)
    info.name = config.project_name or info.name
    if commands is None:
        commands = await probe('commands', discover_commands, (root, config), {})
    info.warnings.extend(getattr(commands, 'warnings', []))
    info.test_command = commands['test'].argv if 'test' in commands else None
    changes = await probe('changes', collect_changes, (root,), ChangeSet(error='Git changes unavailable'))
    info.changed_files = changes.files
    info.changes_error = changes.error
    info.affected_commands = await probe('impact', affected_commands, (root, commands, changes.files), [])
    if changes.error:
        info.warnings.append(changes.error)
    probes = {
        'runtime': (detect_runtime, (root, info.languages), {}),
        'git': (detect_git, (root, changes), None),
        'docker': (detect_docker, (root,), None),
        'ports': (detect_ports, (root,), []),
    }
    values = await asyncio.gather(*(probe(name, fn, args, fallback) for name, (fn, args, fallback) in probes.items()))
    for name, value in zip(probes, values):
        setattr(info, name, value)
    if info.docker and info.docker.error:
        info.warnings.append(f'docker: {info.docker.error}')
    return info
