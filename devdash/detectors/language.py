"""Language, framework, and package manager detection."""

from __future__ import annotations

import re
import fnmatch
from devdash.metadata import read_json, read_text
from pathlib import Path


def detect_languages(root: Path) -> list[str]:
    """Detect programming languages from project marker files."""
    langs: list[str] = []

    if any((root / m).exists() for m in ("pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "requirements.txt")):
        langs.append("Python")

    if (root / "package.json").exists():
        langs.append("TypeScript" if (root / "tsconfig.json").exists() else "JavaScript")

    if any((root / marker).exists() for marker in ("go.mod", "go.work")):
        langs.append("Go")

    if (root / "Cargo.toml").exists():
        langs.append("Rust")

    if any((root / m).exists() for m in ("pom.xml", "build.gradle", "build.gradle.kts")):
        langs.append("Java")

    return langs or ["Unknown"]


def detect_frameworks(root: Path) -> list[str]:
    """Detect frameworks by inspecting dependency files."""
    frameworks: list[str] = []

    # Python deps (scan pyproject.toml + requirements.txt as raw text)
    py_text = ""
    for f in ("pyproject.toml", "requirements.txt"):
        p = root / f
        if p.exists():
            py_text += read_text(p).lower()

    if py_text:
        for key, name in (
            ("fastapi", "FastAPI"), ("django", "Django"), ("flask", "Flask"),
            ("starlette", "Starlette"), ("tornado", "Tornado"),
            ("litestar", "Litestar"), ("sanic", "Sanic"),
        ):
            if key in py_text:
                frameworks.append(name)

    # JS/TS deps
    pkg_path = root / "package.json"
    if pkg_path.exists():
        try:
            pkg = read_json(pkg_path)
            all_deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            for key, name in (
                ("next", "Next.js"), ("react", "React"), ("vue", "Vue"),
                ("nuxt", "Nuxt"), ("svelte", "Svelte"), ("express", "Express"),
                ("@angular/core", "Angular"), ("astro", "Astro"),
            ):
                if key in all_deps:
                    frameworks.append(name)
        except (OSError, ValueError, TypeError, AttributeError):
            raise

    return frameworks


def detect_package_manager(root: Path) -> str | None:
    """Detect the package manager from lock files and config."""
    # Python
    if (root / "uv.lock").exists():
        return "uv"
    if (root / "poetry.lock").exists():
        return "poetry"
    if (root / "Pipfile").exists():
        return "pipenv"
    if (root / "pdm.lock").exists():
        return "pdm"

    if (root / "package.json").exists():
        return detect_node_manager(root)

    if (root / "Cargo.toml").exists():
        return "cargo"
    if any((root / marker).exists() for marker in ("go.mod", "go.work")):
        return "go"
    if (root / "requirements.txt").exists():
        return "pip"

    # Python project with pyproject.toml but no lock file
    if (root / "pyproject.toml").exists():
        return "pip"

    return None


def _local_node_manager(root: Path) -> str | None:
    """Node selection is independent of Python lockfiles in mixed-language roots."""
    try:
        value = read_json(root / "package.json").get("packageManager", "")
        if isinstance(value, str):
            match = re.fullmatch(r"(npm|pnpm|yarn|bun)@\d+(?:\.\d+){0,2}(?:[-+][\w.-]+)?", value)
            if match:
                return match[1]
    except (OSError, ValueError):
        pass
    for filename, manager in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"),
                              ("bun.lock", "bun"), ("bun.lockb", "bun"),
                              ("npm-shrinkwrap.json", "npm"), ("package-lock.json", "npm")):
        if (root / filename).is_file():
            return manager
    return None


def detect_node_manager(root: Path) -> str:
    local = _local_node_manager(root)
    if local:
        return local
    # Inherit only declared workspace membership, not arbitrary ancestor lockfiles.
    for parent in root.parents:
        try:
            package = read_json(parent / "package.json")
            patterns = package.get("workspaces", [])
            if isinstance(patterns, dict):
                patterns = patterns.get("packages", [])
            relative = root.relative_to(parent).parts
            if isinstance(patterns, list) and any(
                isinstance(pattern, str) and len(pattern.split("/")) == len(relative)
                and all(fnmatch.fnmatchcase(part, rule) for part, rule in zip(relative, pattern.split("/")))
                for pattern in patterns
            ):
                return _local_node_manager(parent) or "npm"
        except (OSError, ValueError, AttributeError):
            pass
        if (parent / ".git").exists():
            break
    return "npm"
