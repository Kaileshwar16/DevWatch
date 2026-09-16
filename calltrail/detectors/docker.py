"""Docker discovery using structured CLI output and explicit scopes."""

from __future__ import annotations

import json
from pathlib import Path

from calltrail.models import DockerContainer, DockerInfo
from calltrail.runner import run_sync

COMPOSE_FILES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")


def has_compose_file(root: Path) -> bool:
    return any((root / name).is_file() for name in COMPOSE_FILES)


def detect_docker(root: Path) -> DockerInfo:
    info = DockerInfo(compose_file=has_compose_file(root))
    info.scope = "project" if info.compose_file else "host"
    _, err, rc = run_sync(["docker", "info", "--format", "{{.ServerVersion}}"], cwd=root, timeout=2)
    if rc:
        info.error = "Docker is not installed" if rc == 127 else (err or "Docker daemon unavailable")
        return info
    info.available = True
    command = (["docker", "compose", "ps", "--all", "--format", "json"] if info.compose_file
               else ["docker", "ps", "--all", "--format", "{{json .}}"])
    out, err, rc = run_sync(command, cwd=root, timeout=3)
    if rc:
        info.error = err or "Cannot list containers"
        return info
    if not out.strip():
        return info
    try:
        # Compose versions emit either an array or one JSON object per line.
        if out.lstrip().startswith("["):
            records = json.loads(out)
        else:
            records = [json.loads(line) for line in out.splitlines() if line.strip()]
        for record in records:
            ports = record.get("Ports", "")
            if not ports:
                ports = ", ".join(
                    f"{p.get('URL', '0.0.0.0')}:{p.get('PublishedPort', 0)}->{p.get('TargetPort', 0)}/{p.get('Protocol', 'tcp')}"
                    for p in record.get("Publishers") or []
                )
            info.containers.append(DockerContainer(
                name=record.get("Name") or record.get("Names", ""), image=record.get("Image", ""),
                status=record.get("Status") or record.get("Health", ""), state=record.get("State", ""),
                ports=ports, container_id=record.get("ID", ""),
            ))
    except (ValueError, TypeError, AttributeError) as exc:
        info.error = f"Cannot parse Docker output: {exc}"
    return info
