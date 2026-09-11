"""Data models for DevDash. The UI never knows how tools work — it uses these."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class GitInfo:
    """Git repository information."""

    branch: str = ""
    dirty: bool = False
    modified: int = 0
    added: int = 0
    deleted: int = 0
    untracked: int = 0
    ahead: int = 0
    behind: int = 0
    last_commit: str = ""
    last_commit_time: str = ""
    changed_files: list[str] = field(default_factory=list)


@dataclass
class DockerContainer:
    """A single Docker container."""

    name: str = ""
    image: str = ""
    status: str = ""
    state: str = ""  # running, exited, paused
    ports: str = ""
    container_id: str = ""


@dataclass
class DockerInfo:
    """Docker environment information."""

    available: bool = False
    containers: list[DockerContainer] = field(default_factory=list)
    compose_file: bool = False
    error: str = ""
    scope: str = "host"


@dataclass
class PortInfo:
    """A listening network port."""

    port: int = 0
    pid: int = 0
    process: str = ""
    protocol: str = "TCP"
    address: str = "0.0.0.0"


@dataclass
class TestResult:
    """Result of a test run."""

    command: list[str] = field(default_factory=list)
    output: str = ""
    passed: int = 0
    failed: int = 0
    errors: int = 0
    duration: str = ""
    success: bool = False
    running: bool = False
    returncode: int = 0


@dataclass
class ProjectInfo:
    """Central project model — every panel uses this."""

    name: str = ""
    root: Path = field(default_factory=Path.cwd)
    languages: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    runtime: dict[str, str] = field(default_factory=dict)
    package_manager: str | None = None
    venv: str | None = None
    git: GitInfo | None = None
    docker: DockerInfo | None = None
    ports: list[PortInfo] = field(default_factory=list)
    test_command: list[str] | None = None
    test_result: TestResult | None = None
    has_env: bool = False
    warnings: list[str] = field(default_factory=list)
