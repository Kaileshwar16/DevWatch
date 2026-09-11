"""Language, framework, and package manager detection."""

from __future__ import annotations

import json
from pathlib import Path


def detect_languages(root: Path) -> list[str]:
    """Detect programming languages from project marker files."""
    langs: list[str] = []

    if any((root / m).exists() for m in ("pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "requirements.txt")):
        langs.append("Python")

    if (root / "package.json").exists():
        langs.append("TypeScript" if (root / "tsconfig.json").exists() else "JavaScript")

    if (root / "go.mod").exists():
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
            py_text += p.read_text(errors="replace").lower()

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
            with open(pkg_path) as f:
                pkg = json.load(f)
            all_deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            for key, name in (
                ("next", "Next.js"), ("react", "React"), ("vue", "Vue"),
                ("nuxt", "Nuxt"), ("svelte", "Svelte"), ("express", "Express"),
                ("@angular/core", "Angular"), ("astro", "Astro"),
            ):
                if key in all_deps:
                    frameworks.append(name)
        except Exception:
            pass

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

    # JS — check packageManager field, then lock files
    pkg_path = root / "package.json"
    if pkg_path.exists():
        try:
            with open(pkg_path) as f:
                pm_field = json.load(f).get("packageManager", "")
            for prefix, name in (("pnpm", "pnpm"), ("yarn", "yarn"), ("bun", "bun")):
                if pm_field.startswith(prefix):
                    return name
        except Exception:
            pass
        if (root / "pnpm-lock.yaml").exists():
            return "pnpm"
        if (root / "yarn.lock").exists():
            return "yarn"
        if (root / "bun.lockb").exists() or (root / "bun.lock").exists():
            return "bun"
        if (root / "package-lock.json").exists():
            return "npm"
        return "npm"

    if (root / "Cargo.toml").exists():
        return "cargo"
    if (root / "go.mod").exists():
        return "go"
    if (root / "requirements.txt").exists():
        return "pip"

    # Python project with pyproject.toml but no lock file
    if (root / "pyproject.toml").exists():
        return "pip"

    return None
