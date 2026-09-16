"""Local real repositories/tools only; no downloads or arbitrary internet fixtures."""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from devdash.commands import Command, discover_commands
from devdash.config import DevDashConfig
from devdash.execution import execute_command
from devdash.outcomes import ExecutionState as S, ExecutionReason as R
from devdash.runner import run_process
from devdash.tasks import TaskManager


class RepositoryIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    async def asyncTearDown(self):
        self.temp.cleanup()

    @unittest.skipUnless(shutil.which('npm'), 'npm unavailable')
    async def test_node_missing_dependency_is_unavailable(self):
        (self.root/'package.json').write_text(json.dumps({'scripts': {'test:unit':'jest'}}))
        command = discover_commands(self.root, DevDashConfig())['test:unit']
        result = await execute_command(command, self.root)
        self.assertEqual((result.state, result.reason), (S.UNAVAILABLE, R.DEPENDENCY_MISSING))
        self.assertFalse((self.root/'node_modules').exists())

    @unittest.skipUnless(shutil.which('npm'), 'npm unavailable')
    async def test_node_project_passes(self):
        (self.root/'package.json').write_text(json.dumps({'scripts': {'test':'node --test example.test.cjs'}}))
        (self.root/'example.test.cjs').write_text("const test=require('node:test'); test('works',()=>{});\n")
        command = discover_commands(self.root, DevDashConfig())['test']
        result = await execute_command(command, self.root)
        self.assertEqual(result.state, S.PASSED, result.output)

    async def test_python_real_assertions_pass_and_fail(self):
        # unittest supplies a dependency-free real test run in every supported Python.
        (self.root/'pyproject.toml').touch()
        tests = self.root/'tests'
        tests.mkdir()
        test = tests/'test_example.py'
        for expected in (S.FAILED, S.PASSED):
            test.write_text('import unittest\nclass Example(unittest.TestCase):\n'
                            f' def test_result(self): self.assertTrue({expected == S.PASSED!r})\n')
            command = discover_commands(self.root, DevDashConfig())['test']
            # Suppress bytecode, so same-second fixture edits cannot reuse old code.
            command.env['PYTHONDONTWRITEBYTECODE'] = '1'
            result = await execute_command(command, self.root)
            self.assertEqual(result.state, expected, result.output)

    async def test_pytest_repository(self):
        import importlib.util
        if importlib.util.find_spec('pytest') is None:
            self.skipTest('pytest unavailable in test environment')
        (self.root/'pyproject.toml').write_text('[tool.pytest.ini_options]\n')
        (self.root/'test_example.py').write_text('def test_example():\n assert 1 == 1\n')
        command = Command('test', [sys.executable, '-m', 'pytest', '-q'], cwd=self.root)
        result = await execute_command(command, self.root)
        self.assertEqual(result.state, S.PASSED, result.output)

    @unittest.skipUnless(shutil.which('go'), 'Go unavailable')
    async def test_go_module(self):
        (self.root/'go.mod').write_text('module example.test/devwatch\ngo 1.20\n')
        (self.root/'example_test.go').write_text('package demo\nimport "testing"\nfunc TestExample(t *testing.T) {}\n')
        command = discover_commands(self.root, DevDashConfig())['test']
        command.env.update({'GOTOOLCHAIN':'local', 'GOPROXY':'off'})
        result = await execute_command(command, self.root, timeout=60)
        self.assertEqual(result.state, S.PASSED, result.output)

    @unittest.skipUnless(shutil.which('go') and os.name == 'posix' and os.geteuid() != 0, 'requires Go and non-root POSIX permissions')
    async def test_real_go_unreadable_directory(self):
        (self.root/'go.mod').write_text('module example.test/devwatch\ngo 1.20\n')
        blocked = self.root/'runtime-data'
        blocked.mkdir()
        blocked.chmod(0)
        try:
            command = discover_commands(self.root, DevDashConfig())['test']
            result = await execute_command(command, self.root)
            self.assertEqual((result.state, result.reason), (S.ERROR, R.DISCOVERY_FAILED))
            self.assertIn("runtime-data: permission denied", result.detail)
            # Also exercise the real Go output classifier, bypassing filesystem preflight.
            actual = await run_process(['go','test','./...'], self.root, env={'GOTOOLCHAIN':'local','GOPROXY':'off'})
            self.assertEqual((actual.state, actual.reason), (S.ERROR, R.DISCOVERY_FAILED), actual.output)
        finally:
            blocked.chmod(0o700)

    @unittest.skipUnless(shutil.which('cargo'), 'Cargo unavailable')
    async def test_rust_project_offline(self):
        (self.root/'Cargo.toml').write_text('[package]\nname="fixture"\nversion="0.1.0"\nedition="2021"\n')
        (self.root/'src').mkdir()
        (self.root/'src/lib.rs').write_text('#[test]\nfn works() { assert_eq!(2+2,4); }\n')
        command = discover_commands(self.root, DevDashConfig())['test']
        command.env['CARGO_NET_OFFLINE'] = 'true'
        result = await execute_command(command, self.root, timeout=60)
        self.assertEqual(result.state, S.PASSED, result.output)

    async def test_timeout_cancel_and_immediate_stop(self):
        manager = TaskManager(self.root)
        command = Command('slow', [sys.executable, '-c', 'import time; time.sleep(10)'], timeout=.05)
        try:
            run = manager.start(command)
            await run.task
            self.assertEqual(run.result.state, S.TIMEOUT)
            for _ in range(5):
                run = manager.start(command)
                await manager.stop('slow')
                self.assertEqual(run.result.state, S.CANCELLED)
            run = manager.start(command)
            await asyncio.sleep(.05)
            await manager.stop('slow')
            self.assertIn(run.result.state, (S.TIMEOUT,S.CANCELLED))
        finally:
            await manager.shutdown()

    async def test_cwd_removed_after_start_and_exit_stop_race(self):
        directory = self.root/'transient'
        directory.mkdir()
        ready = asyncio.Event()
        task = asyncio.create_task(run_process([sys.executable, '-c', 'import time; print("ready",flush=True); time.sleep(.1)'],
                                               directory, lambda _: ready.set()))
        await ready.wait()
        directory.rmdir()
        self.assertEqual((await task).state, S.PASSED)
        manager = TaskManager(self.root)
        try:
            for _ in range(10):
                run = manager.start(Command('exit', [sys.executable, '-c', 'pass']))
                await asyncio.sleep(.01)
                await manager.stop('exit')
                self.assertIn(run.result.state, (S.CANCELLED,S.PASSED))
                self.assertTrue(run.task.done())
        finally:
            await manager.shutdown()


@unittest.skipUnless(os.environ.get('DEVDASH_LIVE_DOCKER') == '1', 'opt-in live Docker smoke')
class DockerIntegrationTests(unittest.TestCase):
    def test_live_daemon_and_compose_json(self):
        from devdash.detectors.docker import detect_docker
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            info = detect_docker(root)
            self.assertTrue(info.available, info.error)
            (root/'compose.yaml').write_text('services:\n  fixture:\n    image: busybox:stable\n')
            # Only info/ps: no image pulls, containers, networks or volumes created.
            info = detect_docker(root)
            self.assertTrue(info.available, info.error)
            self.assertFalse(info.error)
            self.assertEqual(info.scope, 'project')
            subprocess.run(['docker','compose','version'], check=True, capture_output=True)
