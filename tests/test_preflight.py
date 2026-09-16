"""Temporary project environments; preflight never starts a project command."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from calltrail.commands import Command, discover_commands
from calltrail.config import CallTrailConfig
from calltrail.preflight import preflight_command
from calltrail.outcomes import ExecutionReason as R, ExecutionState as S


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_structure_cwd_and_executable(self):
        for command, reason in ((Command('empty', []), R.CONFIGURATION_ERROR),
                                (Command('cwd', ['x'], cwd=self.root/'missing'), R.INVALID_WORKING_DIRECTORY),
                                (Command('tool', ['/missing/tool']), R.COMMAND_NOT_FOUND)):
            with self.subTest(reason=reason):
                self.assertEqual(preflight_command(command, self.root).reason, reason)

    def test_missing_jest_and_installed_local_binary(self):
        (self.root/'package.json').write_text(json.dumps({'scripts': {'test:unit': 'jest'}}))
        command = Command('test', ['npm', 'run', 'test:unit'])
        with patch('calltrail.preflight.resolve_executable', side_effect=lambda value, *_: '/npm' if value == 'npm' else None):
            result = preflight_command(command, self.root)
            self.assertEqual(result.reason, R.DEPENDENCY_MISSING)
            self.assertEqual(result.result().state, S.UNAVAILABLE)
            binary = self.root/'node_modules/.bin/jest'
            binary.parent.mkdir(parents=True)
            binary.write_text('#!/bin/sh\nexit 99\n')
            binary.chmod(0o755)
            self.assertTrue(preflight_command(command, self.root).runnable)

    def test_go_permission_hazard(self):
        real = os.scandir
        child = self.root/'runtime/data'
        child.mkdir(parents=True)
        def scan(path):
            if Path(path) == child:
                raise PermissionError('denied')
            return real(path)
        with patch('calltrail.preflight.os.scandir', side_effect=scan), \
             patch('calltrail.preflight.resolve_executable', return_value='/go'):
            result = preflight_command(Command('test', ['go', 'test', './...']), self.root)
        self.assertEqual(result.reason, R.DISCOVERY_FAILED)
        self.assertEqual(result.result().state, S.ERROR)
        self.assertIn('runtime/data', result.errors[0].detail)

    def test_no_scripts_imports_or_env_reads(self):
        (self.root/'package.json').write_text(json.dumps({'scripts': {'test': 'node side-effect.js'}}))
        (self.root/'side-effect.js').write_text('throw Error("must not execute")')
        (self.root/'.env').write_text('SECRET=must-not-read')
        with patch('subprocess.Popen', side_effect=AssertionError('spawn forbidden')):
            commands = discover_commands(self.root, CallTrailConfig())
            preflight_command(commands['test'], self.root)

    def test_no_pytest_in_selected_venv(self):
        venv = self.root/'.venv'
        venv.mkdir()
        (venv/'pyvenv.cfg').write_text('home = /missing')
        binary = venv/'bin/python'
        binary.parent.mkdir()
        binary.symlink_to(sys.executable)
        result = preflight_command(Command('test', [str(binary), '-m', 'pytest']), self.root)
        self.assertEqual(result.reason, R.DEPENDENCY_MISSING)
