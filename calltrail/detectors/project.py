"""Project root detection and basic project info."""

from __future__ import annotations

from calltrail.metadata import read_json, read_toml, read_text
from pathlib import Path



def find_project_root(start: Path | None = None) -> Path:
    """Find the project root directory.

    Use the nearest project marker, including packages inside monorepos.
    """
    start = (start or Path.cwd()).expanduser().resolve()
    if not start.is_dir():
        raise ValueError(f"Not a directory: {start}")

    # Walk up looking for project markers
    markers = [
        "pyproject.toml", "setup.py", "package.json", "go.mod",
        "Cargo.toml", "pom.xml", "build.gradle", ".git",
        "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
        "Makefile", ".calltrail.toml", "requirements.txt", "setup.cfg", "Pipfile",
        "build.gradle.kts", "go.work", "justfile", "Taskfile.yml", "Taskfile.yaml",
    ]
    current = start.resolve()
    while True:
        if any((current / m).exists() for m in markers):
            return current
        if current == current.parent:
            break
        current = current.parent

    return start.resolve()


def detect_project_name(root: Path) -> str:
    """Detect project name from config files, falling back to dir name."""
    # pyproject.toml
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            name = read_toml(pyproject).get("project", {}).get("name")
            if isinstance(name, str) and name.strip():
                return name
        except (OSError, ValueError, AttributeError, IndexError):
            pass

    # package.json
    pkg = root / "package.json"
    if pkg.exists():
        try:
            name = read_json(pkg).get("name")
            if isinstance(name, str) and name.strip():
                return name
        except (OSError, ValueError, AttributeError, IndexError):
            pass

    # go.mod
    gomod = root / "go.mod"
    if gomod.exists():
        try:
            for line in read_text(gomod).splitlines():
                if line.startswith("module "):
                    return line.split()[1].split("/")[-1]
        except (OSError, ValueError, AttributeError, IndexError):
            pass

    # Cargo.toml
    cargo = root / "Cargo.toml"
    if cargo.exists():
        try:
            name = read_toml(cargo).get("package", {}).get("name")
            if isinstance(name, str) and name.strip():
                return name
        except (OSError, ValueError, AttributeError, IndexError):
            pass

    return root.name


def detect_venv(root: Path) -> str | None:
    """Detect virtual environment directory."""
    for d in (".venv", "venv", "env"):
        if any((root / d / p).is_file() for p in ("bin/python", "Scripts/python.exe")):
            return d
    return None


def detect_env_files(root: Path) -> bool:
    """Check if .env files exist (never reads contents)."""
    return any(
        (root / f).exists()
        for f in (".env", ".env.local", ".env.development", ".env.production")
    )
