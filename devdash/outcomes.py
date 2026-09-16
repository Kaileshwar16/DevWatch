"""Execution semantics shared by the runner, CLI and dashboard.

Nonzero exit status alone never establishes a failed check. Output recognizers
are deliberately small and require positive evidence from a known test format.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class ExecutionState(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    RUNNING = "running"
    PENDING = "pending"


class ExecutionReason(str, Enum):
    ASSERTION_FAILURE = "assertion_failure"
    COMMAND_NOT_FOUND = "command_not_found"
    DEPENDENCY_MISSING = "dependency_missing"
    INVALID_WORKING_DIRECTORY = "invalid_working_directory"
    DISCOVERY_FAILED = "discovery_failed"
    PERMISSION_DENIED = "permission_denied"
    CONFIGURATION_ERROR = "configuration_error"
    PROCESS_ERROR = "process_error"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    UNKNOWN_ERROR = "unknown_error"


@dataclass
class ExecutionResult:
    state: ExecutionState = ExecutionState.PENDING
    exit_code: int | None = None
    reason: ExecutionReason | None = None
    summary: str = ""
    detail: str = ""
    output: str = ""
    suggestion: str = ""


def classify(argv: list[str], code: int, output: str) -> ExecutionResult:
    """Classify a completed process; spawn/timeout/cancel are handled upstream."""
    state, reason, summary = ExecutionState.ERROR, ExecutionReason.UNKNOWN_ERROR, "Command could not complete its checks"
    clean = re.sub(r"\x1b\[[0-9;]*m", "", output)
    lower = clean.lower()
    if code == 0:
        return ExecutionResult(ExecutionState.PASSED, code, summary="Command completed successfully", output=output)
    if code < 0:
        return ExecutionResult(ExecutionState.ERROR, code, ExecutionReason.PROCESS_ERROR,
                               f"Process terminated by signal {-code}", output=output)
    # Infrastructure evidence takes precedence even if some tests failed earlier.
    if "pattern ./...:" in lower or "error collecting " in lower or "errors during collection" in lower:
        reason = ExecutionReason.DISCOVERY_FAILED
        summary = "Go package discovery failed" if "pattern ./...:" in lower else "Test discovery failed"
    elif ((code == 127 and re.search(r": (?:command )?not found\s*$", lower, re.M))
          or re.search(r"^.*(?:python[^:]*): no module named (?:pytest|unittest)\s*$", lower, re.M)):
        state, reason, summary = ExecutionState.UNAVAILABLE, ExecutionReason.DEPENDENCY_MISSING, "Required executable or module could not be resolved"
    elif "permission denied" in lower:
        reason, summary = ExecutionReason.PERMISSION_DENIED, "Permission denied accessing a required resource"
    elif any(marker in lower for marker in ("[build failed]", "could not compile", "test suite failed to run",
                                             "cannot connect to the docker daemon", "importerror while loading", "modulenotfounderror:", "importerror:")):
        reason, summary = ExecutionReason.PROCESS_ERROR, "Runtime or build setup prevented checks from completing"
    elif any(marker in lower for marker in ("configuration error", "configerror", "invalid configuration")):
        reason, summary = ExecutionReason.CONFIGURATION_ERROR, "Invalid project configuration"
    elif _test_failure(clean):
        state, reason, summary = ExecutionState.FAILED, ExecutionReason.ASSERTION_FAILURE, "Checks ran and reported failures"
    # Keep a small useful excerpt; raw output remains separately available.
    detail = "\n".join(clean.splitlines()[-12:])[-4000:]
    return ExecutionResult(state, code, reason, summary, detail, output)


def _test_failure(output: str) -> bool:
    patterns = (
        r"^\s*--- FAIL: \S+",  # Go test, not a package/build FAIL line
        r"^.*\b[1-9]\d* failed\b.*\bin [\d.]+s",  # pytest summary
        r"^\s*Tests:\s*.*\b[1-9]\d* failed\b",  # Jest
        r"^test result: FAILED\..*\b[1-9]\d* failed",  # Cargo
        r"^FAILED \(failures=[1-9]\d*(?:, skipped=\d+)?\)$",  # unittest assertions only
    )
    # Pytest setup/collection errors are not assertion failures.
    if re.search(r"\b[1-9]\d* errors?\b.*\bin [\d.]+", output):
        return False
    return any(re.search(pattern, output, re.M) for pattern in patterns)
