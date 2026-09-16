"""One preflight/execution path for manual, affected, CLI and dashboard tasks."""
import asyncio
from pathlib import Path
from devdash.commands import Command
from devdash.preflight import preflight_command
from devdash.runner import run_process


async def execute_command(command: Command, root: Path, on_output=None, timeout=None):
    preflight = await asyncio.to_thread(preflight_command, command, root)
    command.preflight = preflight
    if not preflight.runnable:
        result = preflight.result()
        if on_output:
            on_output(result.summary)
            if result.detail:
                on_output(result.detail)
        return result
    return await run_process(command.argv, command.cwd or root, on_output,
                             command.effective_timeout(timeout), env=command.env)
