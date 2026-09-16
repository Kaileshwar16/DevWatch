"""Docker actions — start/stop containers via docker CLI."""

from __future__ import annotations

from pathlib import Path

from calltrail.runner import run_async


async def compose_up(cwd: Path) -> tuple[str, int]:
    """Run docker compose up -d."""
    out, err, rc = await run_async(
        ["docker", "compose", "up", "-d"], cwd=cwd, timeout=60.0,
    )
    return "\n".join(part for part in (out, err) if part), rc


async def compose_down(cwd: Path) -> tuple[str, int]:
    """Run docker compose down."""
    out, err, rc = await run_async(
        ["docker", "compose", "down"], cwd=cwd, timeout=30.0,
    )
    return "\n".join(part for part in (out, err) if part), rc


async def stop_container(name: str) -> tuple[str, int]:
    """Stop a specific container."""
    out, err, rc = await run_async(
        ["docker", "stop", name], timeout=15.0,
    )
    return out or err, rc


async def start_container(name: str) -> tuple[str, int]:
    """Start a specific container."""
    out, err, rc = await run_async(
        ["docker", "start", name], timeout=15.0,
    )
    return out or err, rc


async def restart_container(name: str) -> tuple[str, int]:
    """Restart a specific container."""
    out, err, rc = await run_async(
        ["docker", "restart", name], timeout=15.0,
    )
    return out or err, rc
