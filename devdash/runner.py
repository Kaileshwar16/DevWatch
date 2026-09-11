"""Run tools without a shell, with project environments and process cleanup."""

from __future__ import annotations

import asyncio
import codecs
import os
import signal
import subprocess
from collections import deque
from collections.abc import Callable
from pathlib import Path


def python_executable(root: Path) -> str:
    for directory in (".venv", "venv", "env"):
        for relative in ("bin/python", "Scripts/python.exe"):
            candidate = root / directory / relative
            if candidate.is_file():
                return str(candidate.resolve() if os.name == "nt" else candidate.absolute())
    return "python" if os.name == "nt" else "python3"


def project_environment(cwd: Path | None) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if cwd:
        for directory in (".venv", "venv", "env"):
            venv = cwd / directory
            binary = venv / ("Scripts" if os.name == "nt" else "bin")
            if (binary / ("python.exe" if os.name == "nt" else "python")).is_file():
                env["VIRTUAL_ENV"] = str(venv.absolute())
                env["PATH"] = str(binary.absolute()) + os.pathsep + env.get("PATH", "")
                env.pop("PYTHONHOME", None)
                break
    return env


def run_sync(cmd: list[str], cwd: Path | None = None, timeout: float = 10.0) -> tuple[str, str, int]:
    if not cmd:
        return "", "Empty command", 2
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace", cwd=cwd,
            stdin=subprocess.DEVNULL, env=project_environment(cwd),
            start_new_session=os.name == "posix",
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                proc.kill()
            proc.communicate()
            return "", "Command timed out", 124
        # Leading spaces are significant in Git porcelain output.
        return stdout.rstrip("\r\n"), stderr.rstrip("\r\n"), proc.returncode
    except FileNotFoundError as exc:
        return "", f"Cannot run {cmd[0]}: {exc}", 127
    except subprocess.TimeoutExpired:
        return "", "Command timed out", 124
    except OSError as exc:
        return "", str(exc), 126


async def _spawn(cmd: list[str], cwd: Path | None, stderr: int, env: dict[str, str] | None = None):
    return await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=stderr,
        stdin=asyncio.subprocess.DEVNULL, cwd=cwd, env={**project_environment(cwd), **(env or {})},
        start_new_session=os.name == "posix",
    )


async def _terminate(proc: asyncio.subprocess.Process) -> None:
    """Reap the child and terminate descendants in its POSIX process group."""
    if os.name == "posix":
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        # The parent may have exited while descendants still hold output pipes.
        await asyncio.sleep(0.2)
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif proc.returncode is None:
        proc.kill()
    await proc.communicate()


async def run_async(cmd: list[str], cwd: Path | None = None, timeout: float = 10.0) -> tuple[str, str, int]:
    if not cmd:
        return "", "Empty command", 2
    proc = None
    try:
        proc = await _spawn(cmd, cwd, asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
        return stdout.decode(errors="replace").rstrip("\r\n"), stderr.decode(errors="replace").rstrip("\r\n"), proc.returncode or 0
    except asyncio.TimeoutError:
        if proc:
            await _terminate(proc)
        return "", "Command timed out", 124
    except asyncio.CancelledError:
        if proc:
            await _terminate(proc)
        raise
    except OSError as exc:
        return "", f"Cannot run {cmd[0]}: {exc}", 127 if isinstance(exc, FileNotFoundError) else 126


async def run_streaming(
    cmd: list[str], cwd: Path | None = None,
    on_output: Callable[[str], None] | None = None,
    timeout: float | None = 300.0,
    *, env: dict[str, str] | None = None,
) -> tuple[str, int]:
    """Stream on the calling event loop. Retain at most ~2 MiB of recent output.

    Timeout includes both output reading and process exit; cancellation cleans up
    the process group on POSIX. No shell expansion or interactive stdin is used.
    """
    lines: deque[str] = deque()
    retained = 0
    truncated = False
    proc = None

    def emit(line: str) -> None:
        nonlocal retained, truncated
        lines.append(line)
        retained += len(line) + 1
        while retained > 2 * 1024 * 1024 and lines:
            retained -= len(lines.popleft()) + 1
            truncated = True
        if on_output:
            on_output(line)

    def output() -> str:
        return ("[earlier output truncated]\n" if truncated else "") + "\n".join(lines)

    if not cmd:
        emit("Empty command")
        return output(), 2
    try:
        proc = await _spawn(cmd, cwd, asyncio.subprocess.STDOUT, env)

        async def consume() -> None:
            assert proc is not None and proc.stdout is not None
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            pending = ""
            while chunk := await proc.stdout.read(8192):
                pending += decoder.decode(chunk)
                while "\n" in pending:
                    line, pending = pending.split("\n", 1)
                    emit(line.rstrip("\r"))
                if len(pending) >= 8192:
                    emit(pending)
                    pending = ""
            pending += decoder.decode(b"", final=True)
            if pending:
                emit(pending)
            await proc.wait()

        await asyncio.wait_for(consume(), timeout)
        return output(), proc.returncode or 0
    except asyncio.TimeoutError:
        if proc:
            await _terminate(proc)
        emit("[timed out]")
        return output(), 124
    except asyncio.CancelledError:
        if proc:
            await _terminate(proc)
        raise
    except OSError as exc:
        if proc:
            await _terminate(proc)
        emit(f"Cannot run {cmd[0]}: {exc}")
        return output(), 127 if isinstance(exc, FileNotFoundError) else 126
    except Exception:
        if proc:
            await _terminate(proc)
        raise
