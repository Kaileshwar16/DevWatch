"""Run tests and interpret common summaries; exit status is authoritative."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from pathlib import Path

from devdash.models import TestResult
from devdash.runner import run_streaming


async def run_tests(
    command: list[str], cwd: Path, on_output: Callable[[str], None] | None = None,
    timeout: float | None = 300.0,
) -> TestResult:
    started = time.monotonic()
    output, code = await run_streaming(command, cwd, on_output, timeout)
    result = TestResult(command=command, output=output, success=code == 0, returncode=code,
                        duration=f"{time.monotonic() - started:.2f}s")
    _parse_results(result, output)
    return result


def _parse_results(result: TestResult, output: str) -> None:
    output = re.sub(r"\x1b\[[0-9;]*m", "", output)
    cargo = re.findall(r"test result: .*?(\d+) passed;\s*(\d+) failed", output)
    if cargo:
        result.passed = sum(int(passed) for passed, _ in cargo)
        result.failed = sum(int(failed) for _, failed in cargo)
        return
    # Pytest reports failed BEFORE passed. Select its last summary line.
    summaries = [line for line in output.splitlines()
                 if re.search(r"\b\d+ (?:passed|failed|errors?)\b", line) and re.search(r"\bin [\d.]+", line)]
    if summaries:
        summary = summaries[-1]
        for key, field in (("passed", "passed"), ("failed", "failed"), ("errors?", "errors")):
            match = re.search(rf"(\d+) {key}\b", summary)
            setattr(result, field, int(match[1]) if match else 0)
        duration = re.search(r"\bin ([\d.]+[sm]*)", summary)
        if duration:
            result.duration = duration[1]
        return
    unittest_count = re.search(r"Ran (\d+) tests? in ([\d.]+)s", output)
    if unittest_count:
        failed = re.search(r"failures=(\d+)", output)
        errors = re.search(r"errors=(\d+)", output)
        skipped = re.search(r"skipped=(\d+)", output)
        result.failed = int(failed[1]) if failed else 0
        result.errors = int(errors[1]) if errors else 0
        result.passed = max(0, int(unittest_count[1]) - result.failed - result.errors - (int(skipped[1]) if skipped else 0))
        result.duration = f"{unittest_count[2]}s"
        return
    result.passed = len(re.findall(r"^ok\s", output, re.MULTILINE))
    result.failed = len(re.findall(r"^FAIL\s+\S", output, re.MULTILINE))
    if result.passed or result.failed:
        return
    js_summary = re.findall(r"^\s*Tests:\s*(.+)$", output, re.MULTILINE)
    if js_summary:
        for field in ("passed", "failed"):
            match = re.search(rf"(\d+) {field}", js_summary[-1])
            setattr(result, field, int(match[1]) if match else 0)
