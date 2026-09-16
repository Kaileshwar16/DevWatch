"""Concurrent real processes must keep independent logs and stop cleanly."""

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

from calltrail.commands import Command
from calltrail.tasks import TaskManager


class TaskTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.manager = TaskManager(self.root)

    async def asyncTearDown(self):
        await self.manager.shutdown()
        self.directory.cleanup()

    async def ready(self, run):
        async def wait():
            while not run.lines and run.status == "running":
                await asyncio.sleep(.01)
        await asyncio.wait_for(wait(), 5)

    def service(self, name):
        return Command(name, [sys.executable, '-c',
            f'import time; print({name!r}, flush=True); time.sleep(30)'], service=True)

    async def test_services_coexist_with_tests_and_keep_separate_logs(self):
        api = self.manager.start(self.service('api'))
        web = self.manager.start(self.service('web'))
        await asyncio.gather(self.ready(api), self.ready(web))
        test = self.manager.start(Command('test', [sys.executable, '-c', 'print("tests passed")']))
        await asyncio.wait_for(test.task, 5)
        self.assertEqual(test.status, 'completed')
        self.assertEqual(list(api.lines), ['api'])
        self.assertEqual(list(web.lines), ['web'])
        self.assertEqual(list(test.lines), ['tests passed'])
        await self.manager.stop('api')
        self.assertEqual(api.status, 'stopped')
        self.assertEqual(web.status, 'running')
        await self.manager.shutdown()
        self.assertEqual(web.status, 'stopped')

    async def test_duplicate_start_selects_existing_and_restart_replaces_finished(self):
        command = self.service('api')
        first = self.manager.start(command)
        self.assertIs(self.manager.start(command), first)
        await self.manager.stop('api')
        self.assertEqual(first.status, 'stopped')
        second = self.manager.start(command)
        self.assertIsNot(first, second)
        await self.ready(second)

    async def test_cwd_environment_and_configured_timeout(self):
        subdir = self.root / 'api'
        subdir.mkdir()
        command = Command('check', [sys.executable, '-c',
            'import os,time; print(os.getcwd(),os.environ["CALLTRAIL_TEST_VALUE"],flush=True); time.sleep(20)'],
            cwd=subdir, env={'CALLTRAIL_TEST_VALUE': 'configured'}, timeout=.2)
        run = self.manager.start(command)
        await asyncio.wait_for(run.task, 5)
        self.assertEqual(run.status, 'timed out')
        self.assertEqual(run.returncode, 124)
        self.assertIn(f'{subdir} configured', run.lines)

    async def test_missing_executable_and_invalid_directory_are_failures(self):
        for command in (Command('missing', ['/calltrail-does-not-exist']),
                        Command('cwd', [sys.executable], cwd=self.root / 'missing')):
            run = self.manager.start(command)
            await run.task
            self.assertEqual(run.status, 'unavailable')
            self.assertTrue(run.lines)

    async def test_noisy_service_log_is_bounded(self):
        run = self.manager.start(Command('noisy', [sys.executable, '-c', 'print("x" * 3000000)']))
        await asyncio.wait_for(run.task, 5)
        self.assertTrue(run.truncated)
        self.assertLessEqual(run.retained, 512 * 1024)
        self.assertLessEqual(len(run.lines), 2000)

    async def test_shutdown_rejects_new_commands(self):
        await self.manager.shutdown()
        with self.assertRaises(ValueError):
            self.manager.start(self.service('api'))

    async def test_repeated_stop_does_not_interrupt_process_cleanup(self):
        run = self.manager.start(self.service('api'))
        await self.ready(run)
        await asyncio.gather(self.manager.stop('api'), self.manager.stop('api'), self.manager.shutdown())
        self.assertTrue(run.task.cancelled())
        self.assertEqual(run.status, 'stopped')
