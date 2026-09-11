"""Shared dashboard and CLI snapshot collection."""

from __future__ import annotations

import asyncio
from pathlib import Path

from devdash.commands import discover_commands
from devdash.config import DevDashConfig
from devdash.detectors.docker import detect_docker
from devdash.detectors.git import detect_git
from devdash.detectors.language import detect_frameworks, detect_languages, detect_package_manager
from devdash.detectors.ports import detect_ports
from devdash.detectors.project import detect_env_files, detect_project_name, detect_venv
from devdash.detectors.runtime import detect_runtime
from devdash.models import ProjectInfo


async def collect_project(root: Path, config: DevDashConfig) -> ProjectInfo:
    info = ProjectInfo(root=root)
    info.name = config.project_name or detect_project_name(root)
    info.languages = detect_languages(root)
    info.frameworks = detect_frameworks(root)
    info.package_manager = detect_package_manager(root)
    info.venv = detect_venv(root)
    info.has_env = detect_env_files(root)
    commands = discover_commands(root, config)
    info.test_command = commands["test"].argv if "test" in commands else None
    probes = {
        "runtime": (detect_runtime, (root, info.languages)),
        "git": (detect_git, (root,)),
        "docker": (detect_docker, (root,)),
        "ports": (detect_ports, (root,)),
    }
    results = await asyncio.gather(
        *(asyncio.to_thread(fn, *args) for fn, args in probes.values()),
        return_exceptions=True,
    )
    for name, result in zip(probes, results):
        if isinstance(result, Exception):
            info.warnings.append(f"{name}: {result}")
        else:
            setattr(info, name, result)
    if info.docker and info.docker.error:
        info.warnings.append(f"docker: {info.docker.error}")
    return info
