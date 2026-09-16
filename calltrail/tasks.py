"""Session-owned concurrent commands, bounded logs, and deterministic shutdown."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from calltrail.commands import Command
from calltrail.execution import execute_command
from calltrail.outcomes import ExecutionResult, ExecutionState, ExecutionReason


@dataclass
class TaskRun:
    command: Command
    status: str = "running"
    result: ExecutionResult = field(default_factory=lambda: ExecutionResult(ExecutionState.RUNNING))
    returncode: int | None = None
    started: float = field(default_factory=time.monotonic)
    finished: float | None = None
    lines: deque[str] = field(default_factory=deque)
    retained: int = 0
    truncated: bool = False
    stopping: bool = False
    task: asyncio.Task | None = None

    @property
    def duration(self) -> float:
        return (self.finished or time.monotonic()) - self.started

    def append(self, line: str) -> None:
        # Bound even a single pathological error message or line.
        if len(line) > 65536:
            line = line[-65536:]
            self.truncated = True
        self.lines.append(line)
        self.retained += len(line) + 1
        while self.retained > 512 * 1024 or len(self.lines) > 2000:
            self.retained -= len(self.lines.popleft()) + 1
            self.truncated = True


class TaskManager:
    """Each command may run once at a time; services and tasks can coexist."""

    def __init__(self, root: Path, timeout: float | None = None,
                 on_change: Callable[[TaskRun, str | None], None] | None = None):
        self.root = root
        self.timeout = timeout
        self.on_change = on_change
        self.runs: dict[str, TaskRun] = {}
        self.closing = False

    def _changed(self, run: TaskRun, line: str | None = None) -> None:
        if self.on_change:
            self.on_change(run, line)

    def start(self, command: Command) -> TaskRun:
        if self.closing:
            raise ValueError("The dashboard is shutting down")
        existing = self.runs.get(command.name)
        if existing and existing.status == "running":
            return existing
        if sum(run.status == "running" for run in self.runs.values()) >= 16:
            raise ValueError("16 commands are already running. Stop one before starting another.")
        if len(self.runs) >= 50 and command.name not in self.runs:
            oldest = next(name for name, run in self.runs.items() if run.status != "running")
            del self.runs[oldest]
        run = TaskRun(command)
        self.runs[command.name] = run
        run.task = asyncio.create_task(self._execute(run), name=f"calltrail:{command.name}")
        return run

    async def _execute(self, run: TaskRun) -> None:
        def output(line: str) -> None:
            run.append(line)
            self._changed(run, line)

        try:
            run.result = await execute_command(
                run.command, self.root, output, self.timeout,
            )
            run.returncode = run.result.exit_code
            # Retain historical lifecycle strings for Python callers; UI uses result.state.
            run.status = {ExecutionState.PASSED: "completed", ExecutionState.TIMEOUT: "timed out"}.get(
                run.result.state, run.result.state.value)
        except asyncio.CancelledError:
            run.status = "stopped"
            run.result = ExecutionResult(ExecutionState.CANCELLED, reason=ExecutionReason.CANCELLED, summary="Command cancelled")
            output("[cancelled]")
            raise
        except Exception as exc:
            run.status = "error"
            run.result = ExecutionResult(ExecutionState.ERROR, 126, ExecutionReason.PROCESS_ERROR, "Execution error", str(exc))
            run.returncode = 126
            output(f"Error: {exc}")
        finally:
            run.finished = time.monotonic()
            self._changed(run)

    async def stop(self, name: str) -> None:
        run = self.runs.get(name)
        if run and run.task and not run.task.done():
            if not run.stopping:
                run.stopping = True
                run.task.cancel()
            await asyncio.gather(run.task, return_exceptions=True)
            # Cancellation may happen before the coroutine's first instruction.
            if run.status == "running":
                run.status = "stopped"
                run.result = ExecutionResult(ExecutionState.CANCELLED, reason=ExecutionReason.CANCELLED, summary="Command cancelled")
                run.finished = time.monotonic()
                self._changed(run)

    async def run_sequence(self, commands: list[Command],
                           on_start: Callable[[TaskRun], None] | None = None) -> list[TaskRun]:
        """Run each distinct invocation once, continuing after failures.

        Cancellation (including stopping the active run) ends the queue. Awaiting
        the owned task propagates cancellation through the existing runner cleanup.
        """
        results = []
        seen = set()
        for command in commands:
            identity = (tuple(command.argv), (command.cwd or self.root).resolve(),
                        tuple(sorted(command.env.items())), command.effective_timeout(self.timeout))
            if identity in seen or self.closing:
                continue
            seen.add(identity)
            # Reuse aliases of an invocation that is already running in this session.
            run = next((run for run in self.runs.values() if run.status == "running"
                        and run.command.argv == command.argv
                        and (run.command.cwd or self.root).resolve() == identity[1]
                        and run.command.env == command.env
                        and run.command.effective_timeout(self.timeout) == identity[3]), None)
            run = run or self.start(command)
            if on_start:
                on_start(run)
            await run.task
            results.append(run)
        return results

    async def shutdown(self) -> None:
        self.closing = True
        await asyncio.gather(*(self.stop(name) for name in list(self.runs)))
