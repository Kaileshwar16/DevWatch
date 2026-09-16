"""Exercise keyboard workflows against Textual's headless terminal driver."""

import asyncio
import json
import os
import signal
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from textual.widgets import RichLog

from calltrail.app import CallTrailApp
from calltrail.changes import ChangedFile
from calltrail.commands import discover_commands
from calltrail.config import CallTrailConfig
from calltrail.impact import affected_commands
from calltrail.screens.impact import ImpactScreen
from calltrail.models import DockerInfo, GitInfo, ProjectInfo
from calltrail.screens.commands import CommandsScreen
from calltrail.screens.docker import DockerScreen
from calltrail.screens.git import GitScreen
from calltrail.screens.tasks import TasksScreen


class AppTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.write_config('print("3 passed in 0.1s")')
        self.info = ProjectInfo(root=self.root, name='demo', git=GitInfo(branch='main'), docker=DockerInfo())
        self.patches = [
            patch('calltrail.app.collect_project', side_effect=self.collect),
            patch('calltrail.screens.docker.detect_docker', return_value=DockerInfo()),
            patch('calltrail.screens.git.git_status', return_value=('On branch main', 0)),
            patch('calltrail.screens.git.git_log_short', return_value=('abc initial', 0)),
            patch('calltrail.screens.git.git_diff_stat', return_value=('Staged:\nfile.py', 0)),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    async def collect(self, root, config, commands=None):
        self.info.test_command = config.commands.get('test')
        return self.info

    def write_config(self, code):
        (self.root / '.calltrail.toml').write_text('[commands]\ntest = ' + json.dumps([sys.executable, '-c', code]) + '\n')

    async def wait_for(self, predicate):
        for _ in range(200):
            if predicate():
                return
            await asyncio.sleep(.01)
        self.fail('Dashboard did not reach expected state')

    async def test_run_tests_and_refresh_preserves_output(self):
        app = CallTrailApp(self.root, interval=0)
        async with app.run_test(size=(110, 40)) as pilot:
            await self.wait_for(lambda: app._project_ready)
            await pilot.press('t')
            await self.wait_for(lambda: app._command_task and app._command_task.done())
            await pilot.pause()
            self.assertTrue(app._info.test_result.success)
            self.assertEqual(app._info.test_result.passed, 3)
            before = [line.text for line in app.output_panel.lines]
            self.assertTrue(any('3 passed' in line for line in before))
            await pilot.press('r')
            await pilot.pause()
            self.assertEqual([line.text for line in app.output_panel.lines], before)

    async def test_command_picker_runs_selected_task(self):
        app = CallTrailApp(self.root, interval=0)
        async with app.run_test() as pilot:
            await self.wait_for(lambda: app._project_ready)
            await pilot.press('c')
            self.assertIsInstance(app.screen, CommandsScreen)
            await pilot.press('enter')
            await self.wait_for(lambda: app._command_task and app._command_task.done())
            self.assertTrue(app._info.test_result.success)
            self.assertNotIsInstance(app.screen, CommandsScreen)

    async def test_stop_long_running_service_and_quit(self):
        (self.root / '.calltrail.toml').write_text('[services.api]\ncommand = ' + json.dumps([
            sys.executable, '-c', 'import time; print("ready", flush=True); time.sleep(20)']) + '\nport = 8000\n')
        app = CallTrailApp(self.root, interval=0)
        async with app.run_test() as pilot:
            await self.wait_for(lambda: app._project_ready)
            await pilot.press('c', 'enter')
            await self.wait_for(lambda: app._command_task is not None)
            await pilot.pause(.1)
            task = app._command_task
            await pilot.press('x')
            self.assertTrue(task.cancelled())
            await pilot.press('c', 'enter')
            await self.wait_for(lambda: app._command_task is not task)
            new_task = app._command_task
            await pilot.press('q')
            self.assertTrue(new_task.done())

    async def test_detail_navigation_refreshes_on_return(self):
        app = CallTrailApp(self.root, interval=0)
        async with app.run_test() as pilot:
            await self.wait_for(lambda: app._project_ready)
            await pilot.press('g')
            self.assertIsInstance(app.screen, GitScreen)
            await pilot.press('l', 'd', 'escape')
            await pilot.press('d')
            self.assertIsInstance(app.screen, DockerScreen)
            await pilot.pause()
            await pilot.press('u')  # No compose file: must not run Docker.
            self.assertFalse(app.screen._busy)
            await pilot.press('escape')
            self.assertNotIsInstance(app.screen, DockerScreen)
            await pilot.press('r')
            await pilot.pause()
            self.assertTrue(app._project_ready)

    async def test_compose_failure_output_is_retained(self):
        (self.root / 'compose.yaml').touch()
        app = CallTrailApp(self.root, interval=0)
        with patch('calltrail.screens.docker.compose_up', return_value=('daemon error', 1)) as action:
            async with app.run_test() as pilot:
                await self.wait_for(lambda: app._project_ready)
                await pilot.press('d')
                await pilot.pause()
                await pilot.press('u')
                await pilot.pause()
                action.assert_awaited_once_with(self.root)
                text = '\n'.join(line.text for line in app.screen.query_one(RichLog).lines)
                self.assertIn('daemon error', text)
                self.assertIn('Exit 1', text)

    async def test_small_terminal_and_invalid_config_refresh(self):
        app = CallTrailApp(self.root, interval=0)
        async with app.run_test(size=(60, 24)) as pilot:
            await self.wait_for(lambda: app._project_ready)
            self.assertTrue(app.query_one('#dashboard').has_class('narrow'))
            (self.root / '.calltrail.toml').write_text('[commands]\ntest = 42\n')
            await pilot.press('r')
            await pilot.pause()
            self.assertIn('commands.test', app._last_error)
            self.assertEqual(app._info.name, 'demo')

    async def test_concurrent_services_log_selection_and_quit(self):
        config = '[commands]\ntest = ' + json.dumps([sys.executable, '-c', 'print("3 passed in 0.1s")']) + '\n'
        for name in ('api', 'web'):
            config += f'[services.{name}]\ncommand = ' + json.dumps([
                sys.executable, '-c', f'import time; print("{name} ready",flush=True); time.sleep(30)']) + '\n'
        (self.root / '.calltrail.toml').write_text(config)
        app = CallTrailApp(self.root, interval=0)
        async with app.run_test(size=(110, 40)) as pilot:
            await self.wait_for(lambda: app._project_ready)
            for name in ('api', 'web'):
                await pilot.press('c', *name, 'enter')
                await self.wait_for(lambda: f'service:{name}' in app._manager.runs and app._manager.runs[f'service:{name}'].lines)
            await pilot.press('t')
            await self.wait_for(lambda: app._manager.runs.get('test') and app._manager.runs['test'].status == 'completed')
            self.assertTrue(app._info.test_result.success)
            self.assertEqual(app._manager.runs['service:api'].status, 'running')
            await pilot.press('a')
            self.assertIsInstance(app.screen, TasksScreen)
            await pilot.press('enter')
            self.assertEqual(app._selected_run, 'service:api')
            displayed = '\n'.join(line.text for line in app.output_panel.lines)
            self.assertIn('api ready', displayed)
            self.assertNotIn('web ready', displayed)
            await pilot.press('x')
            self.assertEqual(app._manager.runs['service:api'].status, 'stopped')
            self.assertEqual(app._manager.runs['service:web'].status, 'running')
            await pilot.press('q')
            self.assertTrue(all(run.task.done() for run in app._manager.runs.values()))

    async def test_search_no_results_and_escape(self):
        app = CallTrailApp(self.root, interval=0)
        async with app.run_test() as pilot:
            await self.wait_for(lambda: app._project_ready)
            await pilot.press('c', *'no-match', 'enter')
            self.assertIsInstance(app.screen, CommandsScreen)
            self.assertIsNone(app._command_task)
            await pilot.press('escape')
            self.assertNotIsInstance(app.screen, CommandsScreen)

    @unittest.skipUnless(os.name == 'posix', 'POSIX termination handlers')
    async def test_termination_stops_tasks_and_restores_signal_handlers(self):
        previous = signal.getsignal(signal.SIGTERM)
        self.write_config('import time; print("ready",flush=True); time.sleep(30)')
        app = CallTrailApp(self.root, interval=0)
        async with app.run_test() as pilot:
            await self.wait_for(lambda: app._project_ready)
            await pilot.press('t')
            await self.wait_for(lambda: app._manager.runs.get('test') and app._manager.runs['test'].lines)
            app._handle_signal(signal.SIGTERM)
            await asyncio.wait_for(app._shutdown_task, 5)
            self.assertEqual(app.exit_signal, signal.SIGTERM)
            self.assertEqual(app._manager.runs['test'].status, 'stopped')
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)

    def prepare_impact(self, code='print("affected executed")', queued=False):
        config = '[commands.check]\ncommand = ' + json.dumps([sys.executable, '-c', code]) + '\npaths = ["src/**"]\n'
        if queued:
            config += '[commands.after]\ncommand = ' + json.dumps([
                sys.executable, '-c', 'print("after executed")']) + '\npaths = ["src/**"]\n'
        (self.root / '.calltrail.toml').write_text(config)
        commands = discover_commands(self.root, CallTrailConfig.load(self.root))
        self.info.changed_files = [ChangedFile('src/auth/token.py', ' ', 'M')]
        self.info.affected_commands = affected_commands(self.root, commands, self.info.changed_files)

    async def test_impact_view_explains_and_runs_affected_via_session(self):
        self.prepare_impact()
        app = CallTrailApp(self.root, interval=0)
        async with app.run_test(size=(110, 40)) as pilot:
            await self.wait_for(lambda: app._project_ready)
            await pilot.press('i')
            self.assertIsInstance(app.screen, ImpactScreen)
            rendered = '\n'.join(line.text for line in app.screen.query_one(RichLog).lines)
            self.assertIn('src/auth/token.py', rendered)
            self.assertIn('rule: src/**', rendered)
            self.assertEqual(app._manager.runs, {})
            await pilot.press('r')
            await self.wait_for(lambda: app._impact_task and app._impact_task.done())
            self.assertNotIsInstance(app.screen, ImpactScreen)
            run = app._manager.runs['check']
            self.assertEqual(run.status, 'completed')
            self.assertIn('affected executed', run.lines)
            self.assertEqual(app._selected_run, 'check')
            await pilot.press('a')
            self.assertIsInstance(app.screen, TasksScreen)

    async def test_empty_impact_view_does_not_start_commands(self):
        app = CallTrailApp(self.root, interval=0)
        async with app.run_test(size=(60, 24)) as pilot:
            await self.wait_for(lambda: app._project_ready)
            await pilot.press('i', 'r')
            self.assertIsInstance(app.screen, ImpactScreen)
            self.assertEqual(app._manager.runs, {})
            rendered = '\n'.join(line.text for line in app.screen.query_one(RichLog).lines)
            self.assertIn('No affected commands detected.', rendered)
            await pilot.press('escape')
            self.assertNotIsInstance(app.screen, ImpactScreen)

    async def test_impact_stop_cancels_queue_and_repeated_run_does_not_duplicate(self):
        self.prepare_impact('import time; print("ready",flush=True); time.sleep(30)', queued=True)
        app = CallTrailApp(self.root, interval=0)
        async with app.run_test() as pilot:
            await self.wait_for(lambda: app._project_ready)
            await pilot.press('i', 'r')
            await self.wait_for(lambda: app._manager.runs.get('check') and app._manager.runs['check'].lines)
            first = app._impact_task
            await pilot.press('i', 'r')
            self.assertIs(app._impact_task, first)
            await pilot.press('x')
            await self.wait_for(lambda: app._impact_task.done())
            self.assertEqual(app._manager.runs['check'].status, 'stopped')
            self.assertNotIn('after', app._manager.runs)

    async def test_impact_quit_stops_batch(self):
        self.prepare_impact('import time; print("ready",flush=True); time.sleep(30)', queued=True)
        app = CallTrailApp(self.root, interval=0)
        async with app.run_test() as pilot:
            await self.wait_for(lambda: app._project_ready)
            await pilot.press('i', 'r')
            await self.wait_for(lambda: app._manager.runs.get('check') and app._manager.runs['check'].lines)
            await pilot.press('q')
            self.assertTrue(app._impact_task.done())
            self.assertEqual(app._manager.runs['check'].status, 'stopped')
            self.assertNotIn('after', app._manager.runs)


    async def test_unavailable_and_error_are_not_rendered_as_test_failures(self):
        from calltrail.outcomes import ExecutionState
        for argv, expected in ((['/calltrail-missing-runner'], ExecutionState.UNAVAILABLE),
                               ([sys.executable, '-c', 'print("pattern ./...: open runtime/data: permission denied"); raise SystemExit(1)'], ExecutionState.ERROR)):
            (self.root / '.calltrail.toml').write_text('[commands]\ntest = ' + json.dumps(argv) + '\n')
            app = CallTrailApp(self.root, interval=0)
            async with app.run_test(size=(110, 40)) as pilot:
                await self.wait_for(lambda: app._project_ready)
                await pilot.press('t')
                await self.wait_for(lambda: app._command_task and app._command_task.done())
                await pilot.pause()
                result = app._manager.runs['test'].result
                self.assertEqual(result.state, expected)
                rendered = '\n'.join(line.text for line in app.output_panel.lines)
                self.assertIn(expected.value.upper(), rendered)
                self.assertNotIn('FAIL ', rendered)

    async def test_quit_during_command_startup(self):
        from calltrail.outcomes import ExecutionState
        app = CallTrailApp(self.root, interval=0)
        async with app.run_test():
            await self.wait_for(lambda: app._project_ready)
            app._start_command('test')
            await app.action_quit()
            run = app._manager.runs['test']
            self.assertTrue(run.task.done())
            self.assertEqual(run.result.state, ExecutionState.CANCELLED)
