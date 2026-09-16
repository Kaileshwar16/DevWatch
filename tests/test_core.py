"""Behavioral coverage for project discovery, configuration and CLI workflows."""

import contextlib
import io
import json
import os
import subprocess
import sys
import signal
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from calltrail.actions.tests import _parse_results
from calltrail.cli import initialize, main
from calltrail.commands import discover_commands
from calltrail.config import ConfigError, CallTrailConfig, command_args
from calltrail.detectors.docker import detect_docker
from calltrail.detectors.git import detect_git
from calltrail.detectors.project import find_project_root
from calltrail.detectors.tests import detect_test_command
from calltrail.models import ProjectInfo, TestResult
from calltrail.doctor import check_commands


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_nearest_package_wins_inside_monorepo(self):
        (self.root / '.git').mkdir()
        package = self.root / 'packages' / 'api'
        source = package / 'src'
        source.mkdir(parents=True)
        (package / 'pyproject.toml').touch()
        self.assertEqual(find_project_root(source), package)

    def test_plain_directory_and_config_only_project(self):
        with patch("pathlib.Path.exists", return_value=False):
            self.assertEqual(find_project_root(self.root), self.root)
        (self.root / '.calltrail.toml').touch()
        nested = self.root / 'src'
        nested.mkdir()
        self.assertEqual(find_project_root(nested), self.root)
        with self.assertRaises(ValueError):
            find_project_root(self.root / 'missing')

    def test_js_package_manager_and_custom_scripts(self):
        (self.root / 'package.json').write_text(json.dumps({
            'packageManager': 'pnpm@9.0.0',
            'scripts': {'test': 'vitest run', 'lint': 'eslint .', 'dev': 'vite'},
        }))
        commands = discover_commands(self.root, CallTrailConfig())
        self.assertEqual(commands['test'].argv, ['pnpm', 'run', 'test'])
        self.assertEqual(commands['lint'].argv, ['pnpm', 'run', 'lint'])

    def test_python_venv_and_uv_runner(self):
        (self.root / 'pyproject.toml').write_text('[tool.pytest.ini_options]\n')
        python = self.root / '.venv' / 'bin' / 'python'
        python.parent.mkdir(parents=True)
        python.touch()
        self.assertEqual(detect_test_command(self.root, ['Python']), [str(python), '-m', 'pytest'])
        (self.root / 'uv.lock').touch()
        self.assertEqual(detect_test_command(self.root, ['Python']), ['uv', 'run', '--no-sync', '--offline', '--no-env-file', '--no-python-downloads', 'python', '-m', 'pytest'])

    def test_unittest_suite(self):
        tests = self.root / 'tests'
        tests.mkdir()
        (tests / 'test_example.py').write_text('import unittest\n')
        command = detect_test_command(self.root, ['Python'])
        self.assertEqual(command[-5:], ['-m', 'unittest', 'discover', '-s', 'tests'])

    def test_configuration_validation_and_service(self):
        for data in ({'commands': []}, {'commands': {'test': ''}},
                     {'commands': {'test': [5]}}, {'commands': {'test': '"'}},
                     {'services': {'api': {'command': 'python', 'port': True}}},
                     {'services': {'api': {'command': 'python', 'port': 65536}}},
                     {'project': {'name': 123}}):
            with self.subTest(data=data), self.assertRaises(ConfigError):
                CallTrailConfig(data)
        config = CallTrailConfig({'commands': {'test': ['echo', 'a b']},
                               'services': {'api': {'command': 'python -m http.server', 'port': 8000}}})
        commands = discover_commands(self.root, config)
        self.assertEqual(commands['test'].argv, ['echo', 'a b'])
        self.assertTrue(commands['service:api'].service)
        self.assertEqual(commands['service:api'].port, 8000)
        self.assertEqual(command_args('echo "hello world"'), ['echo', 'hello world'])

    def test_init_round_trip_and_no_overwrite(self):
        path = initialize(self.root)
        self.assertEqual(CallTrailConfig.load(self.root).project_name, self.root.name)
        before = path.read_bytes()
        with self.assertRaises(FileExistsError):
            initialize(self.root)
        self.assertEqual(path.read_bytes(), before)

    def test_cli_invalid_config_and_missing_path_are_readable(self):
        for path in (self.root / 'missing', self.root):
            (self.root / '.calltrail.toml').write_text('[commands]\ntest = 1\n')
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = main([str(path), '--list-commands'])
            self.assertEqual(code, 2)
            self.assertNotIn('Traceback', err.getvalue())

    def test_cli_json_schema(self):
        out = io.StringIO()
        info = ProjectInfo(name='demo', root=self.root)
        with patch('calltrail.cli.collect_project', return_value=info), contextlib.redirect_stdout(out):
            self.assertEqual(main([str(self.root), '--json']), 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data['root'], str(self.root))
        self.assertEqual(data['commands'], {})
        self.assertEqual(data['warnings'], [])

    def test_cli_task_streams_and_preserves_exit_code(self):
        (self.root / '.calltrail.toml').write_text(
            '[commands]\ncheck = ' + json.dumps([sys.executable, '-c', 'print("hello"); raise SystemExit(7)']) + '\n')
        result = subprocess.run([sys.executable, '-m', 'calltrail', str(self.root), '--run', 'check'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(result.stdout, 'hello\n')

    def test_cli_timeout_and_unknown_task(self):
        (self.root / '.calltrail.toml').write_text(
            '[commands]\nslow = ' + json.dumps([sys.executable, '-c', 'import time; time.sleep(20)']) + '\n')
        result = subprocess.run([sys.executable, '-m', 'calltrail', str(self.root), '--run', 'slow', '--timeout', '.1'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 124, result.stderr)
        self.assertIn('[timed out]', result.stdout)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main([str(self.root), '--run', 'missing']), 2)

    def test_git_preserves_spaces_and_rename_records(self):
        def git(*args):
            return subprocess.run(['git', *args], cwd=self.root, check=True, capture_output=True)
        git('init')
        git('config', 'user.email', 'test@example.invalid')
        git('config', 'user.name', 'CallTrail Tests')
        (self.root / 'first file.txt').write_text('before\n')
        git('add', '.')
        git('commit', '-m', 'initial')
        (self.root / 'first file.txt').write_text('after\n')
        info = detect_git(self.root)
        self.assertEqual(info.modified, 1)
        self.assertEqual(info.changed_files, ['first file.txt'])
        git('add', '.')
        git('commit', '-m', 'update')
        git('mv', 'first file.txt', 'renamed file.txt')
        info = detect_git(self.root)
        self.assertEqual(info.changed_files, ['renamed file.txt'])

    def test_docker_empty_compose_never_falls_back_to_host(self):
        (self.root / 'compose.yaml').touch()
        with patch('calltrail.detectors.docker.run_sync', side_effect=[('28', '', 0), ('[]', '', 0)]) as run:
            info = detect_docker(self.root)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(info.scope, 'project')
        self.assertEqual(info.containers, [])
        self.assertIn('--all', run.call_args.args[0])

    def test_docker_json_lines_and_array(self):
        (self.root / 'compose.yaml').touch()
        row = {'ID': 'abc', 'Name': 'api', 'State': 'exited', 'Publishers': [
            {'URL': '127.0.0.1', 'PublishedPort': 8000, 'TargetPort': 80, 'Protocol': 'tcp'}]}
        for output in (json.dumps([row]), json.dumps(row)):
            with patch('calltrail.detectors.docker.run_sync', side_effect=[('28', '', 0), (output, '', 0)]):
                info = detect_docker(self.root)
            self.assertEqual(info.containers[0].container_id, 'abc')
            self.assertEqual(info.containers[0].ports, '127.0.0.1:8000->80/tcp')

    def test_summary_counts_failures_before_passes(self):
        result = TestResult()
        _parse_results(result, '=== 2 failed, 3 passed, 1 error in 1.20s ===')
        self.assertEqual((result.passed, result.failed, result.errors), (3, 2, 1))
        _parse_results(result, '=== 4 failed in 0.25s ===')
        self.assertEqual((result.passed, result.failed), (0, 4))

    def test_cargo_multiple_summaries(self):
        result = TestResult()
        _parse_results(result, 'test result: ok. 5 passed; 0 failed\ntest result: FAILED. 1 passed; 2 failed')
        self.assertEqual((result.passed, result.failed), (6, 2))

    def test_extended_config_rejects_typos_and_invalid_options(self):
        invalid = [
            {'command': ['echo'], 'timout': 2},
            {'command': ['echo'], 'timeout': float('nan')},
            {'command': ['echo'], 'timeout': True},
            {'command': ['echo'], 'timeout': -1},
            {'command': ['echo'], 'env': {'BAD=NAME': 'value'}},
            {'command': ['echo'], 'env': {'PORT': 8000}},
            {'command': ['echo'], 'cwd': ''},
            {'description': 'missing command'},
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ConfigError):
                CallTrailConfig({'commands': {'check': value}})
        with self.assertRaisesRegex(ConfigError, 'unknown option'):
            CallTrailConfig({'comands': {'test': 'echo'}})

    def test_extended_cli_command_uses_cwd_env_and_timeout(self):
        (self.root / 'api').mkdir()
        argv = [sys.executable, '-c', 'import os; print(os.path.basename(os.getcwd()),os.environ["CALLTRAIL_VALUE"])']
        (self.root / '.calltrail.toml').write_text(
            '[commands.check]\ncommand = ' + json.dumps(argv) + '\ncwd = "api"\ntimeout = 5\n'
            'description = "Check environment"\nenv = { CALLTRAIL_VALUE = "hello" }\n')
        result = subprocess.run([sys.executable, '-m', 'calltrail', str(self.root), '--run', 'check'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'api hello\n')

    def test_doctor_checks_paths_without_executing_commands(self):
        marker = self.root / 'must-not-exist'
        config = CallTrailConfig({'commands': {
            'good': [sys.executable, '-c', f'open({str(marker)!r}, "w").close()'],
            'missing': ['/calltrail-does-not-exist'],
            'cwd': {'command': [sys.executable], 'cwd': 'missing'},
        }})
        checks = check_commands(self.root, discover_commands(self.root, config))
        self.assertEqual([check.ok for check in checks], [True, False, False])
        self.assertFalse(marker.exists())

    def test_doctor_cli_exit_codes(self):
        for executable, expected in ((sys.executable, 0), ('/calltrail-does-not-exist', 1)):
            (self.root / '.calltrail.toml').write_text('[commands]\ncheck = ' + json.dumps([executable]) + '\n')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(self.root), '--doctor']), expected)

    def test_json_redacts_configured_environment_values(self):
        (self.root / '.calltrail.toml').write_text(
            '[commands.check]\ncommand = ["echo", "ready"]\nenv = { TOKEN = "secret-value" }\n')
        out = io.StringIO()
        with patch('calltrail.cli.collect_project', return_value=ProjectInfo(root=self.root)), contextlib.redirect_stdout(out):
            self.assertEqual(main([str(self.root), '--json']), 0)
        self.assertNotIn('secret-value', out.getvalue())
        data = json.loads(out.getvalue())
        self.assertEqual(data['schema_version'], 1)
        self.assertEqual(data['commands']['check']['env_keys'], ['TOKEN'])

    def test_ss_preserves_high_ports_and_multiple_addresses(self):
        from calltrail.detectors.ports import _detect_with_ss
        output = 'State Recv-Q Send-Q Local Peer Process\nLISTEN 0 128 127.0.0.1:55000 0.0.0.0:*\nLISTEN 0 128 [::1]:55000 [::]:*\n'
        with patch('calltrail.runner.run_sync', return_value=(output, '', 0)):
            ports = _detect_with_ss()
        self.assertEqual([(p.address, p.port) for p in ports], [('127.0.0.1', 55000), ('::1', 55000)])

    @unittest.skipUnless(os.name == 'posix', 'POSIX signals and process groups')
    def test_cli_sigterm_cleans_up_service_and_descendants(self):
        import psutil
        ready = self.root / 'ready.json'
        code = ('import subprocess,sys,os,json,time; from pathlib import Path; '
                'child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); '
                f'Path({str(ready)!r}).write_text(json.dumps([os.getpid(),child.pid])); time.sleep(30)')
        (self.root / '.calltrail.toml').write_text('[services.api]\ncommand = ' + json.dumps([sys.executable, '-c', code]) + '\n')
        proc = subprocess.Popen([sys.executable, '-m', 'calltrail', str(self.root), '--run', 'service:api'],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline and proc.poll() is None:
                time.sleep(.02)
            self.assertTrue(ready.exists())
            pids = json.loads(ready.read_text())
            proc.send_signal(signal.SIGTERM)
            _, err = proc.communicate(timeout=5)
            self.assertEqual(proc.returncode, 143, err)
            for pid in pids:
                if psutil.pid_exists(pid):
                    self.assertEqual(psutil.Process(pid).status(), psutil.STATUS_ZOMBIE)
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.communicate()
