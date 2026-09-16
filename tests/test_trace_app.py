"""Headless Trace navigation, history, indexing responsiveness and preview."""
import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Input, RichLog

from calltrail.app import CallTrailApp
from calltrail.models import ProjectInfo
from calltrail.screens.trace import TraceScreen


class TraceAppTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        (self.root/'demo.py').write_text('def main(): a()\ndef a(): b()\ndef b(): pass\n'
                                        'if __name__ == "__main__": main()\n')
        self.mock = patch('calltrail.app.collect_project', return_value=ProjectInfo(root=self.root, name='demo'))
        self.mock.start()

    async def asyncTearDown(self):
        self.mock.stop()
        self.directory.cleanup()

    async def wait_for(self, predicate):
        for _ in range(400):
            if predicate():
                return
            await asyncio.sleep(.01)
        self.fail('Trace screen did not reach expected state')

    async def test_incoming_outgoing_entry_paths_history_and_preview(self):
        app = CallTrailApp(self.root, interval=0)
        async with app.run_test(size=(110, 40)) as pilot:
            await self.wait_for(lambda: app._project_ready)
            await pilot.press('f')
            self.assertIsInstance(app.screen, TraceScreen)
            screen = app.screen
            await self.wait_for(lambda: screen.graph is not None)
            screen.query_one(Input).value = 'b'
            await pilot.press('enter')
            await self.wait_for(lambda: screen.data and screen.data['symbol']['name'] == 'b')
            await pilot.press('enter')
            await self.wait_for(lambda: screen.data['symbol']['name'] == 'a')
            self.assertEqual(screen.history, [('b', 'incoming')])
            await pilot.press('o')
            await self.wait_for(lambda: bool(screen.data['outgoing']))
            self.assertEqual(screen.data['outgoing'][0]['callee']['name'], 'b')
            await pilot.press('escape')
            await self.wait_for(lambda: screen.data['symbol']['name'] == 'b')
            await pilot.press('e')
            await self.wait_for(lambda: bool(screen.data['paths']))
            self.assertEqual(screen.data['paths'][0]['entry_kind'], 'MAIN')
            rendered = '\n'.join(line.text for line in screen.query_one(RichLog).lines)
            self.assertIn('Source preview', rendered)
            self.assertIn('Possible static', rendered)
            await pilot.press('q')
            self.assertNotIsInstance(app.screen, TraceScreen)

    async def test_slow_index_does_not_block_escape(self):
        from calltrail.trace.python import PythonAstProvider
        original = PythonAstProvider.refresh
        def slow(provider):
            time.sleep(.4)
            return original(provider)
        app = CallTrailApp(self.root, interval=0)
        with patch.object(PythonAstProvider, 'refresh', slow):
            async with app.run_test(size=(70, 30)) as pilot:
                await self.wait_for(lambda: app._project_ready)
                await pilot.press('f')
                self.assertIsInstance(app.screen, TraceScreen)
                await pilot.press('escape')
                self.assertNotIsInstance(app.screen, TraceScreen)
                await asyncio.sleep(.5)  # Let the bounded, read-only background worker finish.

    async def test_refresh_invalidates_graph_and_duplicate_selection(self):
        (self.root/'other.py').write_text('def b(): pass')
        app = CallTrailApp(self.root, interval=0)
        async with app.run_test(size=(100, 40)) as pilot:
            await self.wait_for(lambda: app._project_ready)
            await pilot.press('f')
            screen = app.screen
            await self.wait_for(lambda: screen.graph is not None)
            screen.query_one(Input).value = 'b'
            await pilot.press('enter')
            await self.wait_for(lambda: screen.data and len(screen.data['candidates']) == 2)
            await pilot.press('enter')
            await self.wait_for(lambda: screen.data['symbol'] is not None)
            (self.root/'other.py').unlink()
            before = screen.graph
            await pilot.press('r')
            await self.wait_for(lambda: screen.graph is not before)
            self.assertEqual(len(screen.graph.lookup('b')), 1)
