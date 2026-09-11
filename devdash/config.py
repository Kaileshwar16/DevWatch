"""Validated, opt-in project commands and services from .devdash.toml."""

from __future__ import annotations

import shlex
import math
from pathlib import Path
from typing import Any

from devdash._toml import tomllib


class ConfigError(ValueError):
    """A configuration problem that can be shown without a traceback."""


def command_args(command: str | list[str]) -> list[str]:
    if isinstance(command, str):
        try:
            args = shlex.split(command)
        except ValueError as exc:
            raise ConfigError(f"Invalid command quoting: {exc}") from exc
    elif isinstance(command, list) and all(isinstance(part, str) for part in command):
        args = list(command)
    else:
        raise ConfigError("Commands must be strings or arrays of strings")
    if not args or not args[0].strip() or any("\0" in arg for arg in args):
        raise ConfigError("Commands must have a nonempty executable and no NUL characters")
    return args


class DevDashConfig:
    def __init__(self, data: dict[str, Any] | None = None):
        self._data = data or {}
        self._check_keys(self._data, {"project", "commands", "services"}, "configuration")
        for section in ("project", "commands", "services"):
            if not isinstance(self._data.get(section, {}), dict):
                raise ConfigError(f"[{section}] must be a table")
        name = self._data.get("project", {}).get("name")
        self._check_keys(self._data.get("project", {}), {"name"}, "project")
        if name is not None and (not isinstance(name, str) or not name.strip()):
            raise ConfigError("project.name must be a nonempty string")
        for name, command in self.commands.items():
            if not name.strip() or name.startswith("service:"):
                raise ConfigError("Command names must be nonempty and cannot start with 'service:'")
            try:
                self._validate_command(command)
            except ConfigError as exc:
                raise ConfigError(f"commands.{name}: {exc}") from exc
        for name, service in self.services.items():
            if not name.strip() or not isinstance(service, dict) or "command" not in service:
                raise ConfigError(f"services.{name} must contain a command")
            try:
                self._validate_command(service, service=True)
            except ConfigError as exc:
                raise ConfigError(f"services.{name}: {exc}") from exc
            port = service.get("port")
            if port is not None and (type(port) is not int or not 1 <= port <= 65535):
                raise ConfigError(f"services.{name}.port must be an integer from 1 to 65535")

    @staticmethod
    def _check_keys(data: dict, allowed: set[str], context: str) -> None:
        unknown = data.keys() - allowed
        if unknown:
            raise ConfigError(f"{context}: unknown option(s): {', '.join(sorted(unknown))}")

    @classmethod
    def _validate_command(cls, value: Any, *, service: bool = False) -> None:
        if not isinstance(value, dict):
            command_args(value)
            return
        cls._check_keys(value, {"command", "cwd", "env", "timeout", "description"} | ({"port"} if service else set()), "command")
        command_args(value.get("command"))
        for key in ("cwd", "description"):
            item = value.get(key)
            if item is not None and (not isinstance(item, str) or not item.strip() or "\0" in item):
                raise ConfigError(f"{key} must be a nonempty string without NUL characters")
        timeout = value.get("timeout")
        if timeout is not None and (type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout < 0):
            raise ConfigError("timeout must be a finite nonnegative number")
        env = value.get("env", {})
        if not isinstance(env, dict) or any(
            not key or "=" in key or "\0" in key or not isinstance(item, str) or "\0" in item
            for key, item in env.items()
        ):
            raise ConfigError("env must map valid environment variable names to strings")

    @classmethod
    def load(cls, project_root: Path) -> DevDashConfig:
        path = project_root / ".devdash.toml"
        try:
            with path.open("rb") as handle:
                return cls(tomllib.load(handle))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError) as exc:
            raise ConfigError(f"{path}: {exc}") from exc

    @property
    def project_name(self) -> str | None:
        return self._data.get("project", {}).get("name")

    @property
    def test_command(self) -> str | list[str] | None:
        value = self.commands.get("test")
        return value.get("command") if isinstance(value, dict) else value

    @property
    def commands(self) -> dict[str, Any]:
        return self._data.get("commands", {})

    @property
    def services(self) -> dict[str, dict[str, Any]]:
        return self._data.get("services", {})
