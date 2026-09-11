"""Test command detection — inspects project files to find the right test runner."""

from __future__ import annotations

import json
from pathlib import Path

from devdash._toml import tomllib
from devdash.detectors.language import detect_package_manager
from devdash.runner import python_executable


def detect_test_command(root: Path, languages: list[str]) -> list[str] | None:
    """Auto-detect the test command for the project.

    Inspects pyproject.toml, package.json, go.mod, Cargo.toml to determine
    the correct test runner without user configuration.
    """
    # Python projects
    if "Python" in languages:
        cmd = _python_test_command(root)
        if cmd:
            manager = detect_package_manager(root)
            if manager in ("uv", "poetry", "pdm", "pipenv"):
                return [manager, "run", "python", "-m", *cmd]
            return [python_executable(root), "-m", *cmd]

    # JS/TS projects
    if "JavaScript" in languages or "TypeScript" in languages:
        cmd = _js_test_command(root)
        if cmd:
            return cmd

    # Go
    if "Go" in languages:
        return ["go", "test", "./..."]

    # Rust
    if "Rust" in languages:
        return ["cargo", "test"]

    # Java (Maven)
    if (root / "pom.xml").exists():
        return ["./mvnw" if (root / "mvnw").is_file() else "mvn", "test"]

    # Java (Gradle)
    if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        return ["./gradlew" if (root / "gradlew").is_file() else "gradle", "test"]

    return None


def _python_test_command(root: Path) -> list[str] | None:
    """Detect Python test command from pyproject.toml or file presence."""
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            with open(pyproject, "rb") as f:
                data = tomllib.load(f)

            # Check for pytest config
            if "tool" in data and "pytest" in data["tool"]:
                return ["pytest"]

            # Check dependencies for pytest
            deps = data.get("project", {}).get("dependencies", [])
            dev_deps = []
            for group in data.get("project", {}).get("optional-dependencies", {}).values():
                dev_deps.extend(group)
            # Also check tool.uv.dev-dependencies
            uv_dev = data.get("tool", {}).get("uv", {}).get("dev-dependencies", [])
            dev_deps.extend(uv_dev)
            for group in data.get("dependency-groups", {}).values():
                dev_deps.extend(dep for dep in group if isinstance(dep, str))

            all_deps = " ".join(deps + dev_deps).lower()
            if "pytest" in all_deps:
                return ["pytest"]

        except Exception:
            pass

    if any((root / marker).is_file() for marker in ("pytest.ini", "conftest.py")):
        return ["pytest"]
    requirements = root / "requirements.txt"
    if requirements.is_file() and "pytest" in requirements.read_text(errors="replace"):
        return ["pytest"]

    # A unittest-only suite does not require installing pytest.
    for test_dir in ("tests", "test"):
        td = root / test_dir
        if td.is_dir():
            samples = list(td.glob("test*.py"))[:20]
            if samples and all("unittest" in p.read_text(errors="replace") for p in samples):
                return ["unittest", "discover", "-s", test_dir]
            return ["pytest"]

    if next(root.glob("test_*.py"), None):
        return ["pytest"]

    return None


def _js_test_command(root: Path) -> list[str] | None:
    """Detect JS/TS test command from package.json scripts."""
    pkg = root / "package.json"
    if not pkg.exists():
        return None

    try:
        with open(pkg) as f:
            data = json.load(f)
        scripts = data.get("scripts", {})
        if "test" in scripts:
            test_script = scripts["test"]
            # Don't return the default "no test specified" script
            if "no test specified" not in test_script:
                manager = detect_package_manager(root)
                return [manager if manager in ("npm", "pnpm", "yarn", "bun") else "npm", "run", "test"]
    except Exception:
        pass

    return None
