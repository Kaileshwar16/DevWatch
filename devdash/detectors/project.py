"""Project root detection and basic project info."""

from __future__ import annotations

import json
from pathlib import Path

from devdash._toml import tomllib


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
        "Makefile", ".devdash.toml", "requirements.txt", "setup.cfg", "Pipfile",
        "build.gradle.kts",
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
            with open(pyproject, "rb") as f:
                name = tomllib.load(f).get("project", {}).get("name")
            if isinstance(name, str) and name.strip():
                return name
        except Exception:
            pass

    # package.json
    pkg = root / "package.json"
    if pkg.exists():
        try:
            with open(pkg) as f:
                name = json.load(f).get("name")
            if isinstance(name, str) and name.strip():
                return name
        except Exception:
            pass

    # go.mod
    gomod = root / "go.mod"
    if gomod.exists():
        try:
            for line in gomod.read_text().splitlines():
                if line.startswith("module "):
                    return line.split()[1].split("/")[-1]
        except Exception:
            pass

    # Cargo.toml
    cargo = root / "Cargo.toml"
    if cargo.exists():
        try:
            with open(cargo, "rb") as f:
                name = tomllib.load(f).get("package", {}).get("name")
            if isinstance(name, str) and name.strip():
                return name
        except Exception:
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
