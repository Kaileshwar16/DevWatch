"""CLI traces share no task execution/discovery side effects."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from devdash.cli import main


class TraceCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root/'demo.py').write_text('def main(): a()\ndef a(): b()\ndef b(): pass\n'
                                        'if __name__ == "__main__": main()\n')

    def invoke(self, *flags):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(['trace', *flags, '--root', str(self.root)])
        return code, out.getvalue(), err.getvalue()

    def test_incoming_outgoing_paths_and_json(self):
        code, out, _ = self.invoke('b')
        self.assertEqual(code, 0)
        self.assertIn('Possible static callers', out)
        self.assertIn('a() [resolved]', out)
        self.assertIn('callsite: demo.py:2', out)
        self.assertIn('b() [resolved]', self.invoke('a', '--outgoing')[1])
        code, out, _ = self.invoke('demo.py:3', '--to-entry', '--json')
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(data['evidence'], 'static')
        self.assertEqual([s['name'] for s in data['paths'][0]['nodes']], ['main', 'a', 'b'])

    def test_ambiguous_missing_unsupported_and_warning(self):
        (self.root/'other.py').write_text('def b(): pass')
        code, out, _ = self.invoke('b')
        self.assertEqual(code, 1)
        self.assertIn('specify file:line', out)
        self.assertIn('other.py:1', out)
        self.assertEqual(self.invoke('missing')[0], 1)
        self.assertIn('only Python', self.invoke('other.go:1')[1])
        (self.root/'broken.py').write_text('def bad(:')
        self.assertIn('Trace available with warnings', self.invoke('a')[1])

    def test_static_path_does_not_spawn_or_collect_environment(self):
        with patch('subprocess.Popen', side_effect=AssertionError('execution forbidden')), \
             patch('devdash.cli.discover_commands', side_effect=AssertionError('unneeded discovery')):
            self.assertEqual(self.invoke('b')[0], 0)

    def test_original_flags_and_trace_directory_still_work(self):
        (self.root/'trace').mkdir()
        with patch('devdash.cli.collect_project') as collect, patch('os.getcwd', return_value=str(self.root)), \
             contextlib.redirect_stdout(io.StringIO()):
            from devdash.models import ProjectInfo
            collect.return_value = ProjectInfo(root=self.root/'trace')
            self.assertEqual(main(['trace', '--json']), 0)

    def test_path_limits_reject_invalid_values(self):
        for option, value in (('--max-depth','0'), ('--max-paths','1001'), ('--max-nodes','-1')):
            with self.subTest(option=option), self.assertRaises(SystemExit) as raised:
                self.invoke('b', option, value)
            self.assertEqual(raised.exception.code, 2)
