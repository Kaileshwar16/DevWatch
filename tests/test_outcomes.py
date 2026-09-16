"""Execution evidence, including deliberately ambiguous failures."""
import asyncio
import sys
import unittest
from calltrail.outcomes import ExecutionReason as R, ExecutionState as S, classify
from calltrail.runner import run_process


class ClassificationTests(unittest.TestCase):
    def test_tool_summaries(self):
        cases = [
            (1, '--- FAIL: TestSomething (0.00s)', S.FAILED, R.ASSERTION_FAILURE),
            (1, '=== 1 failed, 42 passed in 2.84s ===', S.FAILED, R.ASSERTION_FAILURE),
            (1, 'Tests: 2 failed, 100 passed', S.FAILED, R.ASSERTION_FAILURE),
            (101, 'test result: FAILED. 0 passed; 1 failed;', S.FAILED, R.ASSERTION_FAILURE),
            (1, 'FAILED (failures=1)', S.FAILED, R.ASSERTION_FAILURE),
            (1, 'pattern ./...: open data/postgres: permission denied', S.ERROR, R.DISCOVERY_FAILED),
            (127, 'sh: 1: jest: not found', S.UNAVAILABLE, R.DEPENDENCY_MISSING),
            (1, 'ERROR collecting tests/test_a.py', S.ERROR, R.DISCOVERY_FAILED),
            (1, '1 failed, 1 error in 1.2s', S.ERROR, R.UNKNOWN_ERROR),
            (1, 'FAIL example.com/pkg [build failed]', S.ERROR, R.PROCESS_ERROR),
            (1, 'Tests: 1 failed\nTest suite failed to run', S.ERROR, R.PROCESS_ERROR),
            (7, 'something broke', S.ERROR, R.UNKNOWN_ERROR),
            (124, 'application exit', S.ERROR, R.UNKNOWN_ERROR),
            (127, 'application exit', S.ERROR, R.UNKNOWN_ERROR),
            (-9, '', S.ERROR, R.PROCESS_ERROR),
        ]
        for code, output, state, reason in cases:
            with self.subTest(output=output):
                result = classify(['check'], code, output)
                self.assertEqual((result.state, result.reason, result.exit_code), (state, reason, code))
        self.assertEqual(classify(['check'], 0, '').state, S.PASSED)


class ProcessOutcomeTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_is_process_semantics_not_exit_code(self):
        result = await run_process([sys.executable, '-c', 'import time; time.sleep(5)'], timeout=.05)
        self.assertEqual(result.state, S.TIMEOUT)
        result = await run_process([sys.executable, '-c', 'raise SystemExit(124)'])
        self.assertEqual(result.state, S.ERROR)

    async def test_cancel_during_spawn_reaps_child(self):
        from unittest.mock import patch
        from calltrail import runner
        original = runner._spawn_unprotected
        created = asyncio.Event()
        children = []
        async def delayed(*args):
            child = await original(*args)
            children.append(child)
            created.set()
            await asyncio.sleep(.05)
            return child
        with patch.object(runner, '_spawn_unprotected', delayed):
            task = asyncio.create_task(run_process([sys.executable, '-c', 'import time; time.sleep(30)']))
            await created.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertIsNotNone(children[0].returncode)
