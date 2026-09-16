"""Discover runnable tasks without executing project code."""

from __future__ import annotations


from dataclasses import dataclass, field
from devdash.preflight import CommandPreflight
from pathlib import Path

from devdash.config import DevDashConfig, command_args
from devdash.detectors.language import detect_languages, detect_node_manager
from devdash.metadata import read_json, read_toml
from devdash.scopes import project_scopes
from devdash.canonical import canonical_commands
from devdash.preflight import preflight_command
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
    paths: list[str] | None = None
    source: str = "configured"
    preflight: CommandPreflight | None = None
    provenance: str = ".devdash.toml"
    scope: str = "."
    runner: str | None = None

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
                "description": self.description, "paths": self.paths, "source": self.source,
                "preflight": self.preflight.public_dict() if self.preflight else None,
                "provenance": self.provenance, "scope": self.scope, "runner": self.runner}


def _configured(root: Path, name: str, value, *, service: bool = False) -> Command:
    options = value if isinstance(value, dict) else {"command": value}
    cwd = (root / options["cwd"]).resolve() if "cwd" in options else root
    return Command(name, command_args(options["command"]), service, options.get("port"),
                   cwd, options.get("env", {}).copy(), options.get("timeout"), options.get("description", ""),
                   options.get("paths"))


class CommandCatalog(dict[str, Command]):
    """A dict-compatible catalog carrying discovery diagnostics."""
    def __init__(self):
        super().__init__()
        self.warnings: list[str] = []


def discover_commands(root: Path, config: DevDashConfig) -> dict[str, Command]:
    commands = CommandCatalog()
    for scope in project_scopes(root, commands.warnings):
        relative = scope.relative_to(root).as_posix()
        local: dict[str, Command] = {}

        def add(name, argv, provenance, *, fallback=False):
            original = name
            if name in local:
                if local[name].argv == argv:
                    return
                if fallback:
                    name = "fallback-" + name
                else:
                    name = name + ":" + Path(provenance).stem
            serial = 2
            base = name
            while name in local:
                name = f"{base}:{serial}"
                serial += 1
            full_name = name if relative == "." else f"{name}@{relative}"
            local[name] = Command(full_name, argv, cwd=scope, source="detected", provenance=provenance,
                                  scope=relative, runner=argv[0], description=(f"Alternative {original}" if name != original else ""))

        try:
            package_path = scope / "package.json"
            if package_path.is_file():
                package = read_json(package_path)
                scripts = package.get("scripts", {})
                if not isinstance(scripts, dict):
                    raise ValueError("package.json scripts must be an object")
                manager = detect_node_manager(scope)
                for name, script in scripts.items():
                    if (isinstance(script, str) and script.strip() and not name.startswith(("-", "service:"))
                            and "no test specified" not in script):
                        add(name, [manager, "run", name], "package.json")
        except (OSError, ValueError, TypeError) as exc:
            commands.warnings.append(f"{scope / 'package.json'}: {exc}")
        for name, argv, provenance in canonical_commands(scope, commands.warnings):
            add(name, argv, provenance)
        try:
            for manifest in ("pyproject.toml", "Cargo.toml"):
                if (scope / manifest).is_file():
                    read_toml(scope / manifest)
            test = detect_test_command(scope, detect_languages(scope))
            if test:
                provenance = ("Cargo.toml" if test[0] == "cargo" else
                              "package.json" if test[0] in ("npm", "pnpm", "yarn", "bun") else
                              "DevWatch heuristic (Go)" if test[0] == "go" else "DevWatch heuristic (Python)")
                add("test", test, provenance, fallback=True)
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            commands.warnings.append(f"{scope}: test detection: {exc}")
        commands.update((command.name, command) for command in local.values())
    for name, value in config.commands.items():
        commands[name] = _configured(root, name, value)
    for name, service in config.services.items():
        key = f"service:{name}"
        commands[key] = _configured(root, key, service, service=True)
    for command in commands.values():
        command.cwd = command.cwd or root
        if command.source == "configured":
            import os
            command.scope = Path(os.path.relpath(command.cwd, root)).as_posix()
            command.runner = command.argv[0]
        if command.source == "detected" and command.runner == "pipenv":
            command.env["PIPENV_DONT_LOAD_ENV"] = "1"
        # Cheap prerequisites refresh each snapshot; Go's walk runs on doctor/launch.
        command.preflight = preflight_command(command, root, thorough=False)
    return commands
