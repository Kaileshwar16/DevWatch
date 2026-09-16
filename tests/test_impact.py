"""Real Git snapshots and deterministic, explainable affected-check workflows."""

import asyncio
import contextlib
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from devdash.changes import ChangedFile, collect_changes
from devdash.cli import main
from devdash.commands import Command, discover_commands
from devdash.config import ConfigError, DevDashConfig
from devdash.impact import affected_commands, matches_path
from devdash.models import DockerInfo
from devdash.tasks import TaskManager


class GitImpactTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.git('init')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'DevDash Tests')
        self.write('src/auth/token.py', 'original\n')
        self.write('tests/auth/test_token.py', 'original test\n')
        self.commit()

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.root, check=True, capture_output=True)

    def write(self, name, content='changed\n'):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-m', 'snapshot')

    def config(self, commands):
        text = ''
        for name, options in commands.items():
            text += f'[commands.{name}]\n'
            for key, value in options.items():
                text += f'{key} = {json.dumps(value)}\n'
        self.write('.devdash.toml', text)
        return DevDashConfig.load(self.root)

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main([str(self.root), *args])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_clean_repository_and_unborn_repository(self):
        changes = collect_changes(self.root)
        self.assertEqual(changes.files, [])
        self.assertEqual(changes.error, '')
        self.assertEqual(changes.repository_root, self.root)
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(['git', 'init', directory], check=True, capture_output=True)
            path = Path(directory)
            (path / 'new file').touch()
            self.assertTrue(collect_changes(path).files[0].untracked)

    def test_staged_unstaged_untracked_and_deleted(self):
        self.write('src/auth/token.py', 'staged\n')
        self.git('add', '.')
        self.write('src/auth/token.py', 'unstaged\n')
        self.write('new directory/new file.py')
        (self.root / 'tests/auth/test_token.py').unlink()
        files = {change.path: change for change in collect_changes(self.root).files}
        self.assertEqual(set(files), {'src/auth/token.py', 'tests/auth/test_token.py', 'new directory/new file.py'})
        self.assertTrue(files['src/auth/token.py'].staged)
        self.assertTrue(files['src/auth/token.py'].unstaged)
        self.assertTrue(files['new directory/new file.py'].untracked)
        self.assertEqual(files['tests/auth/test_token.py'].worktree_status, 'D')

    def test_rename_matches_old_and_new_paths(self):
        self.git('mv', 'src/auth/token.py', 'src/auth/new token.py')
        changes = collect_changes(self.root)
        self.assertEqual(len(changes.files), 1)
        change = changes.files[0]
        self.assertEqual((change.path, change.original_path, change.index_status),
                         ('src/auth/new token.py', 'src/auth/token.py', 'R'))
        commands = {name: Command(name, ['echo', name], paths=[path]) for name, path in
                    [('old', 'src/auth/token.py'), ('new', 'src/auth/new token.py')]}
        self.assertEqual([item.name for item in affected_commands(self.root, commands, changes.files)], ['old', 'new'])

    def test_unstaged_move_keeps_deleted_and_new_paths(self):
        (self.root / 'src/auth/token.py').rename(self.root / 'src/auth/moved.py')
        changes = collect_changes(self.root)
        self.assertEqual({change.path for change in changes.files}, {'src/auth/token.py', 'src/auth/moved.py'})
        self.assertTrue(any(change.untracked for change in changes.files))

    def test_index_and_worktree_only_changes_are_distinct(self):
        self.write('src/auth/token.py')
        self.git('add', 'src/auth/token.py')
        self.write('tests/auth/test_token.py')
        files = {change.path: change for change in collect_changes(self.root).files}
        self.assertTrue(files['src/auth/token.py'].staged)
        self.assertFalse(files['src/auth/token.py'].unstaged)
        self.assertFalse(files['tests/auth/test_token.py'].staged)
        self.assertTrue(files['tests/auth/test_token.py'].unstaged)

    @unittest.skipUnless(os.name == 'posix', 'POSIX filename characters')
    def test_whitespace_unicode_and_newline_names_are_preserved(self):
        names = [' leading space ', 'line\r\nbreak.py', 'café.py', 'tab\tfile.py']
        for name in names:
            self.write(name)
        self.assertEqual({change.path for change in collect_changes(self.root).files}, set(names))

    def test_worktree_and_subproject_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            worktree = Path(directory) / 'worktree'
            self.git('worktree', 'add', '-b', 'impact-tests', str(worktree))
            (worktree / 'src/auth/token.py').write_text('worktree change')
            changes = collect_changes(worktree / 'src')
            self.assertEqual(changes.repository_root, worktree.resolve())
            self.assertEqual(changes.files[0].path, 'auth/token.py')
            self.assertEqual(collect_changes(self.root).files, [])

    def test_git_unavailable_and_non_repository(self):
        with patch('devdash.runner.subprocess.Popen', side_effect=FileNotFoundError('git missing')):
            changes = collect_changes(self.root)
        self.assertEqual(changes.files, [])
        self.assertIn('git missing', changes.error)
        with tempfile.TemporaryDirectory() as directory:
            changes = collect_changes(Path(directory))
        self.assertIsNone(changes.repository_root)
        self.assertIn('Git changes unavailable', changes.error)

    def test_status_failure_is_explained(self):
        with patch('devdash.changes.run_sync', side_effect=[(str(self.root) + '\n', '', 0), ('', 'failure', 128)]):
            changes = collect_changes(self.root)
        self.assertIn('failure', changes.error)
        self.assertEqual(changes.files, [])

    def test_rules_multiple_matches_no_matches_and_legacy_commands(self):
        config = self.config({
            'auth': {'command': ['echo', 'auth'], 'paths': ['src/auth/**', '**/*.py']},
            'lint': {'command': ['echo', 'lint'], 'paths': ['src/**']},
            'frontend': {'command': ['echo'], 'cwd': 'frontend', 'paths': ['frontend/**']},
            'legacy': {'command': ['echo']},
        })
        commands = discover_commands(self.root, config)
        results = affected_commands(self.root, commands, [ChangedFile('src/auth/token.py', 'M', 'M')])
        self.assertEqual([item.name for item in results], ['auth', 'lint'])
        self.assertEqual(results[0].matched_files, ['src/auth/token.py'])
        self.assertEqual(results[0].matched_patterns, ['src/auth/**', '**/*.py'])
        self.assertEqual(results[0].reasons[0].strategy, 'configured-path')
        self.assertEqual(affected_commands(self.root, commands, [ChangedFile('docs/readme.md')]), [])
        self.assertEqual(affected_commands(self.root, commands, []), [])
        results = affected_commands(self.root, commands, [ChangedFile('frontend/src/login.tsx')])
        self.assertEqual([item.name for item in results], ['frontend'])
        self.assertEqual(results[0].cwd, str(self.root / 'frontend'))

    def test_nearby_python_tests_and_full_suite_fallback(self):
        self.write('pyproject.toml', '[tool.pytest.ini_options]\n')
        self.write('tests/test_token.py')
        commands = discover_commands(self.root, DevDashConfig())
        results = affected_commands(self.root, commands, [ChangedFile('src/auth/token.py')])
        self.assertEqual(results[0].argv, commands['test'].argv)
        self.assertEqual(set(results[0].reasons[0].nearby_tests),
                         {'tests/auth', 'tests/auth/test_token.py', 'tests/test_token.py'})
        for path in ['src/unmapped.py', 'conftest.py', 'pyproject.toml', 'uv.lock', 'tests/deleted.py']:
            with self.subTest(path=path):
                self.assertEqual(len(affected_commands(self.root, commands, [ChangedFile(path)])), 1)

    def test_detected_check_scripts_exclude_servers_and_formatters(self):
        self.write('package.json', json.dumps({'scripts': {name: 'example' for name in
                   ('test', 'test:unit', 'lint', 'check', 'typecheck', 'dev', 'format', 'publish')}}))
        commands = discover_commands(self.root, DevDashConfig())
        results = affected_commands(self.root, commands, [ChangedFile('src/index.ts')])
        self.assertEqual([item.name for item in results], ['test', 'test:unit', 'lint', 'check', 'typecheck'])

    def test_monorepo_scopes_root_fallback_and_shared_files(self):
        commands = {name: Command(name, ['echo', name], cwd=cwd, source='detected') for name, cwd in
                    [('test', self.root), ('test:api', self.root / 'api'), ('test:web', self.root / 'web')]}
        results = affected_commands(self.root, commands, [ChangedFile('api/src/main.py')])
        self.assertEqual([item.name for item in results], ['test:api', 'test'])
        shared = affected_commands(self.root, commands, [ChangedFile('shared/types.py')])
        self.assertEqual({item.name for item in shared}, set(commands))
        self.assertEqual(shared[0].reasons[0].strategy, 'shared-file')
        renamed = affected_commands(self.root, commands, [ChangedFile('web/main.py', 'R', ' ', 'api/main.py')])
        self.assertEqual({item.name for item in renamed}, set(commands))

    def test_affected_cli_and_no_execution_during_discovery(self):
        self.config({'auth': {'command': [sys.executable, '-c', 'raise Exception("must not execute")'],
                             'paths': ['src/auth/**']}})
        self.write('src/auth/token.py')
        code, out, err = self.invoke('--affected')
        self.assertEqual((code, err), (0, ''))
        self.assertIn('M src/auth/token.py', out)
        self.assertIn('Affected commands\n  auth', out)
        self.assertIn('rule: src/auth/**', out)
        self.commit()
        code, out, _ = self.invoke('--run-affected')
        self.assertEqual(code, 0)
        self.assertIn('Working tree is clean.', out)
        self.assertIn('No affected commands detected.', out)
        self.write('README.md')
        self.assertIn('No path rules', self.invoke('--affected')[1])

    def test_run_affected_all_failures_preserve_first_code_and_deduplicate(self):
        first = [sys.executable, '-c', 'print("FIRST_EXECUTED"); raise SystemExit(7)']
        second = [sys.executable, '-c', 'print("SECOND_EXECUTED"); raise SystemExit(9)']
        self.config({name: {'command': command, 'paths': ['src/**', '**/*.py']} for name, command in
                     [('first', first), ('alias', first), ('second', second)]})
        self.write('src/auth/token.py')
        code, out, err = self.invoke('--run-affected')
        self.assertEqual(code, 7)
        self.assertEqual(out.splitlines().count('FIRST_EXECUTED'), 1)
        self.assertEqual(out.splitlines().count('SECOND_EXECUTED'), 1)
        self.assertLess(out.splitlines().index('FIRST_EXECUTED'), out.splitlines().index('SECOND_EXECUTED'))
        self.assertIn('first: exit 7', err)
        self.assertIn('second: exit 9', err)

    def test_run_affected_success_and_unavailable_git_are_successful(self):
        self.config({'check': {'command': [sys.executable, '-c', 'print("success")'], 'paths': ['src/**']}})
        self.write('src/auth/token.py')
        code, out, err = self.invoke('--run-affected')
        self.assertEqual(code, 0)
        self.assertIn('success', out.splitlines())
        self.assertIn('check: exit 0', err)
        with patch('devdash.changes.run_sync', return_value=('', 'Git missing', 127)):
            code, out, err = self.invoke('--run-affected')
        self.assertEqual(code, 0)
        self.assertIn('Git changes unavailable: Git missing', out)
        self.assertIn('No affected commands detected.', out)
        self.assertEqual(err, '')

    def test_run_affected_timeout_continues_and_honors_cwd_env(self):
        self.write('.devdash.toml', '[commands.slow]\ncommand = ' + json.dumps([
            sys.executable, '-c', 'import time; time.sleep(30)']) + '\npaths = ["src/**"]\n'
            '[commands.after]\ncommand = ' + json.dumps([
                sys.executable, '-c', 'import os; print(os.path.basename(os.getcwd()), os.environ["IMPACT_TEST"])']) +
            '\npaths = ["src/**"]\ncwd = "src"\nenv = { IMPACT_TEST = "value" }\n')
        self.write('src/auth/token.py')
        code, out, _ = self.invoke('--run-affected', '--timeout', '.3')
        self.assertEqual(code, 124)
        self.assertIn('src value', out)
        self.assertIn('[timed out]', out)

    def test_json_additive_schema_redacts_env_and_git_status_collected_once(self):
        self.config({'auth': {'command': ['echo'], 'paths': ['src/**']}})
        self.write('src/auth/token.py')
        from devdash.changes import run_sync
        with patch('devdash.discovery.detect_docker', return_value=DockerInfo()), \
             patch('devdash.discovery.detect_ports', return_value=[]), \
             patch('devdash.discovery.detect_runtime', return_value={}), \
             patch('devdash.changes.run_sync', wraps=run_sync) as git:
            code, out, _ = self.invoke('--json')
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data['schema_version'], 1)
        self.assertIn('git', data)
        self.assertIn('commands', data)
        self.assertEqual(data['affected_commands'][0]['name'], 'auth')
        self.assertEqual(data['affected_commands'][0]['matched_files'], ['src/auth/token.py'])
        self.assertEqual(data['affected_commands'][0]['reasons'][0]['strategy'], 'configured-path')
        self.assertIn('index_status', data['changed_files'][0])
        self.assertEqual(sum('status' in call.args[0] for call in git.call_args_list), 1)

    @unittest.skipUnless(os.name == 'posix', 'POSIX signal/process-group cleanup')
    def test_run_affected_signals_reap_descendants_and_stop_queue(self):
        import psutil
        for signum in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(signum=signum):
                ready = self.root / f'ready-{signum}.json'
                after = self.root / 'should-not-run'
                script = ('import os,subprocess,sys,time,json; from pathlib import Path; '
                          'child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); '
                          f'Path({str(ready)!r}).write_text(json.dumps([os.getpid(),child.pid])); time.sleep(30)')
                self.config({
                    'first': {'command': [sys.executable, '-c', script], 'paths': ['**']},
                    'after': {'command': [sys.executable, '-c', f'open({str(after)!r}, "w").close()'], 'paths': ['**']},
                })
                proc = subprocess.Popen([sys.executable, '-m', 'devdash', str(self.root), '--run-affected'],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    deadline = time.monotonic() + 5
                    while not ready.exists() and time.monotonic() < deadline and proc.poll() is None:
                        time.sleep(.02)
                    self.assertTrue(ready.exists())
                    pids = json.loads(ready.read_text())
                    proc.send_signal(signum)
                    _, err = proc.communicate(timeout=5)
                    self.assertEqual(proc.returncode, 128 + signum, err)
                    self.assertFalse(after.exists())
                    for pid in pids:
                        if psutil.pid_exists(pid):
                            self.assertEqual(psutil.Process(pid).status(), psutil.STATUS_ZOMBIE)
                finally:
                    if proc.poll() is None:
                        proc.kill()
                    proc.communicate()


class PathRuleTests(unittest.TestCase):
    def test_glob_semantics(self):
        cases = [
            ('src/a.py', 'src/*.py', True), ('src/auth/a.py', 'src/*.py', False),
            ('src/a.py', 'src/**/*.py', True), ('src/auth/a.py', 'src/**/*.py', True),
            ('a.py', '**/*.py', True), ('a/b/c.py', '**', True),
            ('src/.hidden', 'src/*', True), ('src/A.py', 'src/a.py', False),
            ('a.py', '[ab].p?', True), ('c.py', '[!ab].py', True),
            ('nested/src/a.py', 'src/**', False), ('../src/a.py', '**', False),
        ]
        for path, pattern, expected in cases:
            with self.subTest(path=path, pattern=pattern):
                self.assertEqual(matches_path(path, pattern), expected)

    def test_invalid_paths_configuration(self):
        for paths in ('src/**', None, 1, {}, [1], [''], [' '], ['/src/**'], ['../src'],
                      ['src/../tests'], ['./src'], ['src\\**'], ['C:/src'], ['src/'],
                      ['src//file'], ['src/a**b'], ['src/\0file']):
            with self.subTest(paths=paths), self.assertRaisesRegex(ConfigError, 'commands.check: paths'):
                DevDashConfig({'commands': {'check': {'command': ['echo'], 'paths': paths}}})
        DevDashConfig({'commands': {'check': {'command': ['echo'], 'paths': []}}})


class SequenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_reuses_running_alias_and_cancellation_stops_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = TaskManager(root)
            argv = [sys.executable, '-c', 'import time; print("ready",flush=True); time.sleep(30)']
            active = manager.start(Command('active', argv))
            sequence = asyncio.create_task(manager.run_sequence([
                Command('alias', argv), Command('after', [sys.executable, '-c', 'print("after")'])]))
            try:
                async def ready():
                    while not active.lines:
                        await asyncio.sleep(.01)
                await asyncio.wait_for(ready(), 5)
                self.assertNotIn('alias', manager.runs)
                await manager.stop('active')
                with self.assertRaises(asyncio.CancelledError):
                    await sequence
                self.assertNotIn('after', manager.runs)
            finally:
                await manager.shutdown()

    async def test_same_argv_different_environments_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = TaskManager(Path(directory))
            argv = [sys.executable, '-c', 'import os; print(os.environ["IMPACT_TEST"])']
            try:
                runs = await manager.run_sequence([Command(name, argv, env={'IMPACT_TEST': name})
                                                   for name in ('one', 'two')])
                self.assertEqual([list(run.lines) for run in runs], [['one'], ['two']])
            finally:
                await manager.shutdown()
