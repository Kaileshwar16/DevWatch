"""Bounded scale regressions using temporary repositories, including unusual paths."""
import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from calltrail.changes import ChangedFile, collect_changes
from calltrail.commands import Command, discover_commands
from calltrail.config import CallTrailConfig
from calltrail.detectors.git import detect_git
from calltrail.impact import affected_commands


class ScaleTests(unittest.TestCase):
    def test_thousands_of_changes_hundreds_of_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = {f'check{i}': Command(f'check{i}', ['echo'], paths=[f'pkg{i}/**']) for i in range(200)}
            changes = [ChangedFile(f'pkg{i % 200}/file {i} café.py', ' ', 'M') for i in range(3000)]
            started = time.monotonic()
            selected = affected_commands(root, commands, changes)
            self.assertEqual(len(selected), 200)
            self.assertEqual(sum(len(item.matched_files) for item in selected), 3000)
            self.assertLess(time.monotonic()-started, 15)

    def test_many_manifests_and_directory_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for i in range(600):
                package = root/f'pkg{i:04}'
                package.mkdir()
                (package/'package.json').write_text(json.dumps({'scripts':{'test':'node --test'}}))
            started = time.monotonic()
            commands = discover_commands(root, CallTrailConfig())
            self.assertLessEqual(len(commands), 511)
            self.assertTrue(any('limited to 512' in warning for warning in commands.warnings))
            self.assertLess(time.monotonic()-started, 15)

    def test_long_git_status_detached_head_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.run(['git',*args], cwd=root, check=True, capture_output=True)
            git('init')
            git('config','user.name','CallTrail fixture')
            git('config','user.email','fixture@example.invalid')
            (root/'tracked').write_text('tracked')
            git('add','.')
            git('commit','-m','fixture')
            git('checkout','--detach')
            for i in range(2000):
                (root/f'file {i} café.txt').touch()
            (root/'link').symlink_to('tracked')
            changes = collect_changes(root)
            self.assertEqual(len(changes.files),2001)
            self.assertIn('link', [change.path for change in changes.files])
            self.assertTrue(detect_git(root,changes).branch.startswith('('))
