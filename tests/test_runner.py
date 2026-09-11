"""Real subprocess lifecycle tests; no external developer tools required."""

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path

from devdash.runner import project_environment, run_async, run_streaming, run_sync


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_streaming_callback_uses_current_loop(self):
        loop = asyncio.get_running_loop()
        received = []
        def callback(line):
            self.assertIs(asyncio.get_running_loop(), loop)
            received.append(line)
        out, code = await run_streaming([sys.executable, '-c', 'print("one"); print("two")'], on_output=callback)
        self.assertEqual((out, code), ('one\ntwo', 0))
        self.assertEqual(received, ['one', 'two'])

    async def test_long_line_and_invalid_utf8(self):
        out, code = await run_streaming([sys.executable, '-c', 'import os; os.write(1, b"x" * 100000 + b"\\xff")'])
        self.assertEqual(code, 0)
        self.assertEqual(len(out.replace('\n', '')), 100001)
        self.assertIn('\ufffd', out)

    async def test_missing_executable_is_streamed(self):
        received = []
        _, code = await run_streaming(['/does-not-exist/devdash-test'], on_output=received.append)
        self.assertEqual(code, 127)
        self.assertIn('Cannot run', received[0])

    async def test_timeout_includes_process_after_stdout_closes(self):
        out, code = await run_streaming([sys.executable, '-c',
            'import os,time; os.close(1); os.close(2); time.sleep(20)'], timeout=.1)
        self.assertEqual(code, 124)
        self.assertIn('timed out', out)

    async def test_async_timeout(self):
        _, err, code = await run_async([sys.executable, '-c', 'import time; time.sleep(20)'], timeout=.1)
        self.assertEqual(code, 124)
        self.assertIn('timed out', err)

    @unittest.skipUnless(os.name == 'posix', 'process groups are POSIX-specific')
    async def test_cancellation_stops_parent_and_child(self):
        import psutil
        pids = []
        ready = asyncio.Event()
        def output(line):
            pids.extend(int(pid) for pid in line.split())
            ready.set()
        code = ('import os,subprocess,sys,time; '
                'child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(20)"]); '
                'print(os.getpid(),child.pid,flush=True); time.sleep(20)')
        task = asyncio.create_task(run_streaming([sys.executable, '-c', code], on_output=output))
        try:
            await asyncio.wait_for(ready.wait(), 5)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        for pid in pids:
            if psutil.pid_exists(pid):
                self.assertEqual(psutil.Process(pid).status(), psutil.STATUS_ZOMBIE)

    async def test_output_is_bounded(self):
        out, code = await run_streaming([sys.executable, '-c', 'print("x" * 3000000)'])
        self.assertEqual(code, 0)
        self.assertLess(len(out), 2100000)
        self.assertTrue(out.startswith('[earlier output truncated]'))

    def test_sync_keeps_leading_spaces(self):
        out, _, code = run_sync([sys.executable, '-c', 'print(" M file")'])
        self.assertEqual((out, code), (' M file', 0))

    @unittest.skipUnless(os.name == 'posix', 'POSIX process groups')
    def test_sync_timeout_kills_descendant_holding_output_pipe(self):
        import time
        code = ('import subprocess,sys,time; '
                'subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); time.sleep(30)')
        start = time.monotonic()
        _, _, rc = run_sync([sys.executable, '-c', code], timeout=.1)
        self.assertEqual(rc, 124)
        self.assertLess(time.monotonic() - start, 3)

    def test_project_environment_prepends_venv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / '.venv' / ('Scripts' if os.name == 'nt' else 'bin')
            binary.mkdir(parents=True)
            (binary / ('python.exe' if os.name == 'nt' else 'python')).touch()
            env = project_environment(root)
            self.assertEqual(env['PATH'].split(os.pathsep)[0], str(binary))
            self.assertEqual(env['VIRTUAL_ENV'], str(root / '.venv'))
