"""Repository fixtures for package ownership, metadata and degraded discovery."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from calltrail.commands import discover_commands
from calltrail.config import CallTrailConfig
from calltrail.discovery import collect_project
from calltrail.detectors.language import detect_node_manager
from calltrail.models import DockerInfo


class DetectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, path, text):
        path = self.root/path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def commands(self):
        return discover_commands(self.root, CallTrailConfig())

    def test_package_managers_and_explicit_metadata(self):
        package = self.write('package.json', '{}')
        for lock, manager in [('pnpm-lock.yaml','pnpm'), ('yarn.lock','yarn'), ('package-lock.json','npm'),
                              ('npm-shrinkwrap.json','npm'), ('bun.lock','bun'), ('bun.lockb','bun')]:
            with self.subTest(lock=lock):
                path = self.write(lock, '')
                self.assertEqual(detect_node_manager(self.root), manager)
                package.write_text('{"packageManager":"npm@10.0.0"}')
                self.assertEqual(detect_node_manager(self.root), 'npm')
                package.write_text('{"packageManager":"pnpm-malicious@1"}')
                self.assertEqual(detect_node_manager(self.root), manager)
                package.write_text('{}')
                path.unlink()

    def test_declared_workspace_inherits_manager_without_changing_cwd(self):
        self.write('package.json', '{"packageManager":"yarn@4.0.0","workspaces":["packages/*"]}')
        self.write('packages/web/package.json', '{"scripts":{"test":"jest"}}')
        commands = self.commands()
        self.assertEqual(commands['test@packages/web'].argv, ['yarn','run','test'])
        self.assertEqual(commands['test@packages/web'].cwd, self.root/'packages/web')

    def test_monorepo_owns_correct_cwd(self):
        self.write('api/pyproject.toml', '[tool.pytest.ini_options]\n')
        self.write('web/package.json', '{"scripts":{"test:unit":"jest"}}')
        self.write('web/pnpm-lock.yaml', '')
        self.write('worker/Cargo.toml', '[package]\nname="worker"\nversion="0.1.0"')
        commands = self.commands()
        self.assertEqual(commands['test@api'].cwd, self.root/'api')
        self.assertEqual(commands['test:unit@web'].argv, ['pnpm','run','test:unit'])
        self.assertEqual(commands['test:unit@web'].cwd, self.root/'web')
        self.assertEqual(commands['test@worker'].argv, ['cargo','test'])
        self.assertEqual(commands['test@worker'].provenance, 'Cargo.toml')
        self.assertNotIn('test', commands)

    def test_canonical_go_and_config_precedence(self):
        self.write('go.mod', 'module example.test/demo\ngo 1.20\n')
        self.write('Makefile', 'test:\n\tgo test ./unit\n')
        commands = self.commands()
        self.assertEqual(commands['test'].argv, ['make','test'])
        self.assertEqual(commands['test'].provenance, 'Makefile')
        self.assertEqual(commands['fallback-test'].argv, ['go','test','./...'])
        override = discover_commands(self.root, CallTrailConfig({'commands': {'test': ['echo','configured']}}))
        self.assertEqual(override['test'].argv, ['echo','configured'])
        self.assertEqual(override['test'].source, 'configured')

    def test_static_sources_do_not_execute_and_keep_alternatives(self):
        self.write('justfile', 'test:\n  touch MUST_NOT_EXIST\n')
        self.write('Taskfile.yaml', 'version: "3"\ntasks:\n  test:\n    cmds:\n      - touch MUST_NOT_EXIST\n')
        self.write('.github/workflows/test.yml', 'jobs:\n  test:\n    steps:\n      - run: go test ./unit\n      - run: ${{ secrets.TEST }}\n')
        commands = self.commands()
        self.assertEqual({c.provenance for c in commands.values()}, {'justfile','Taskfile.yaml','.github/workflows/test.yml'})
        self.assertFalse((self.root/'MUST_NOT_EXIST').exists())

    def test_manifest_cache_invalidates(self):
        path = self.write('package.json', '{"scripts":{"test":"node --test"}}')
        self.assertIn('test', self.commands())
        path.write_text('{"scripts":{"lint":"eslint ."}}')
        self.assertNotIn('test', self.commands())
        self.assertIn('lint', self.commands())

    def test_malformed_manifest_does_not_hide_healthy_sibling(self):
        self.write('broken/package.json', '{invalid')
        self.write('good/package.json', '{"scripts":{"test":"node --test"}}')
        commands = self.commands()
        self.assertIn('test@good', commands)
        self.assertTrue(commands.warnings)

    def test_bounded_scopes_ignored_directories_and_symlinks(self):
        for folder in ('node_modules', 'target', '.venv', 'dist', 'build', '__pycache__'):
            self.write(f'{folder}/package.json', '{"scripts":{"test":"jest"}}')
        self.write('good/package.json', '{"scripts":{"test":"node --test"}}')
        (self.root/'cycle').symlink_to(self.root, target_is_directory=True)
        commands = self.commands()
        self.assertEqual(list(commands), ['test@good'])

    def test_mixed_root_node_ignores_python_manager(self):
        self.write('uv.lock', '')
        self.write('package.json', json.dumps({'packageManager':'pnpm@9','scripts':{'test':'jest'}}))
        self.assertEqual(self.commands()['test'].argv[0], 'pnpm')

    def test_init_preserves_package_cwd(self):
        from calltrail.cli import initialize
        self.write('web/package.json', '{"scripts":{"test":"node --test"}}')
        initialize(self.root)
        configured = discover_commands(self.root, CallTrailConfig.load(self.root))
        self.assertEqual(configured['test@web'].cwd, self.root/'web')


class ResilienceTests(unittest.IsolatedAsyncioTestCase):
    async def test_independent_detector_failures_and_safe_debug(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('calltrail.discovery.detect_frameworks', side_effect=RuntimeError('SECRET_VALUE')), \
                 patch('calltrail.discovery.detect_docker', return_value=DockerInfo()), \
                 patch('calltrail.discovery.detect_ports', side_effect=NotImplementedError('unsupported')):
                info = await collect_project(root, CallTrailConfig(), {})
            self.assertEqual(info.name, root.name)
            self.assertEqual(info.ports, [])
            self.assertTrue(any(item.detector == 'frameworks' and not item.ok for item in info.diagnostics))
            from calltrail.diagnostics import diagnostic_report
            self.assertNotIn('SECRET_VALUE', diagnostic_report(info, {}))
            self.assertNotIn('SECRET_VALUE', str(info.warnings))

    async def test_refresh_remains_on_worker_threads(self):
        import threading
        main = threading.get_ident()
        def detect(root):
            self.assertNotEqual(threading.get_ident(), main)
            return []
        with tempfile.TemporaryDirectory() as directory, patch('calltrail.discovery.detect_frameworks', detect), \
             patch('calltrail.discovery.detect_docker', return_value=DockerInfo()):
            await collect_project(Path(directory), CallTrailConfig(), {})
