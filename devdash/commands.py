"""Discover runnable tasks without executing project code."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from devdash.config import DevDashConfig, command_args
from devdash.detectors.language import detect_languages, detect_package_manager
from devdash.detectors.tests import detect_test_command


@dataclass
class Command:
    name: str
    argv: list[str]
    service: bool = False
    port: int | None = None
    cwd: Path | None = None
    env: dict[str, str] = field(default_factory=dict)
    timeout: float | None = None
    description: str = ""

    def effective_timeout(self, override: float | None = None) -> float | None:
        value = override if override is not None else self.timeout
        if value is None:
            value = 0 if self.service else 300
        return value or None

    def public_dict(self) -> dict:
        """Expose environment names, never configured secret values, in snapshots."""
        return {"name": self.name, "argv": self.argv, "service": self.service,
                "port": self.port, "cwd": str(self.cwd) if self.cwd else None,
                "env_keys": sorted(self.env), "timeout": self.timeout,
                "description": self.description}


def _configured(root: Path, name: str, value, *, service: bool = False) -> Command:
    options = value if isinstance(value, dict) else {"command": value}
    cwd = (root / options["cwd"]).resolve() if "cwd" in options else root
    return Command(name, command_args(options["command"]), service, options.get("port"),
                   cwd, options.get("env", {}).copy(), options.get("timeout"), options.get("description", ""))


def discover_commands(root: Path, config: DevDashConfig) -> dict[str, Command]:
    commands: dict[str, Command] = {}
    test = detect_test_command(root, detect_languages(root))
    if test:
        commands["test"] = Command("test", test)
    try:
        package = json.loads((root / "package.json").read_text())
        scripts = package.get("scripts", {})
        manager = detect_package_manager(root)
        manager = manager if manager in ("npm", "pnpm", "yarn", "bun") else "npm"
        if isinstance(scripts, dict):
            for name, script in scripts.items():
                if (isinstance(script, str) and script.strip() and not name.startswith(("-", "service:"))
                        and "no test specified" not in script):
                    commands[name] = Command(name, [manager, "run", name])
    except (OSError, ValueError, AttributeError):
        pass
    for name, command in config.commands.items():
        commands[name] = _configured(root, name, command)
    for name, service in config.services.items():
        key = f"service:{name}"
        commands[key] = _configured(root, key, service, service=True)
    return commands
