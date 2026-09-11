"""Runtime version detection — orchestrates python/node/go/rustc --version."""

from __future__ import annotations

from pathlib import Path

from devdash.runner import run_sync
from devdash.runner import python_executable


def detect_runtime(root: Path, languages: list[str]) -> dict[str, str]:
    """Detect runtime versions for each detected language."""
    runtimes: dict[str, str] = {}
    dispatch = {
        "Python": ("Python", _python_version),
        "JavaScript": ("Node", _node_version),
        "TypeScript": ("Node", _node_version),
        "Go": ("Go", _go_version),
        "Rust": ("Rust", _rust_version),
        "Java": ("Java", _java_version),
    }
    for lang in languages:
        if lang in dispatch:
            label, fn = dispatch[lang]
            if label not in runtimes:
                runtimes[label] = fn(root)
    return runtimes


def _python_version(root: Path) -> str:
    for cmd in (python_executable(root), "python3", "python"):
        out, _, rc = run_sync([cmd, "--version"])
        if rc == 0:
            return out.replace("Python ", "")
    return "n/a"


def _node_version(root: Path) -> str:
    out, _, rc = run_sync(["node", "--version"])
    return out.lstrip("v") if rc == 0 else "n/a"


def _go_version(root: Path) -> str:
    out, _, rc = run_sync(["go", "version"])
    if rc == 0:
        parts = out.split()
        return parts[2].lstrip("go") if len(parts) >= 3 else out
    return "n/a"


def _rust_version(root: Path) -> str:
    out, _, rc = run_sync(["rustc", "--version"])
    if rc == 0:
        parts = out.split()
        return parts[1] if len(parts) >= 2 else out
    return "n/a"


def _java_version(root: Path) -> str:
    out, err, rc = run_sync(["java", "--version"])
    text = out or err
    if rc == 0 and text:
        return text.splitlines()[0].split()[-1] if text.splitlines() else text
    return "n/a"
