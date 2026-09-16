"""Static Python fixtures: no project imports, commands or network access."""
import tempfile
import unittest
from pathlib import Path

from devdash.trace.python import PythonAstProvider
from devdash.trace.graph import CallHierarchy
from devdash.trace.source import IndexLimits


class TraceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.provider = PythonAstProvider(self.root)

    def write(self, path, text):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding='utf-8')
        return file

    def test_index_functions_methods_classes_nested_and_async(self):
        self.write('demo.py', 'def outer():\n def inner(): pass\nclass A:\n async def method(self): pass\n')
        index = self.provider.refresh()
        names = {s.qualified_name: s for s in index.symbols.values()}
        self.assertEqual(set(names), {'<module>', 'outer', 'outer.inner', 'A', 'A.method'})
        self.assertEqual(names['A.method'].kind, 'method')
        self.assertEqual((names['outer'].location.line, names['outer'].end_line), (1, 2))

    def test_broken_source_and_no_execution(self):
        self.write('broken.py', 'def bad(:')
        self.write('ok.py', 'raise RuntimeError("must never execute")\ndef good(): pass\n')
        index = self.provider.refresh()
        self.assertEqual(index.files_indexed, 1)
        self.assertIn('broken.py: SyntaxError', index.warnings[0])

    def test_exclusions_symlinks_boundaries_and_limits(self):
        for folder in ('.venv', 'venv', 'env', 'site-packages', 'node_modules', 'generated'):
            self.write(f'{folder}/ignore.py', 'def hidden(): pass')
        self.write('nested/.git', 'gitdir: elsewhere')
        self.write('nested/ignore.py', 'def hidden(): pass')
        self.write('good.py', 'def good(): pass')
        (self.root/'cycle').symlink_to(self.root, target_is_directory=True)
        self.assertEqual(self.provider.refresh().files_indexed, 1)
        self.write('second.py', 'def second(): pass')
        small = PythonAstProvider(self.root, IndexLimits(max_files=1)).refresh()
        self.assertTrue(small.truncated)

    def test_cache_changes_deletions_and_unicode(self):
        file = self.write('café.py', 'def café(): pass')
        first = self.provider.refresh()
        self.assertEqual(first.files_parsed, 1)
        self.assertEqual(self.provider.refresh().files_parsed, 0)
        file.write_text('def changed(): pass')
        self.assertEqual(self.provider.refresh().files_parsed, 1)
        file.unlink()
        self.assertFalse(self.provider.refresh().symbols)

    def edges(self):
        return self.provider.refresh().relations

    def test_basic_multiple_and_nested_calls(self):
        self.write('demo.py', 'def a():\n c()\ndef b():\n c()\ndef c(): pass\n'
                   'def outer():\n def inner(): c()\n inner()\n')
        self.assertEqual({(r.caller.qualified_name, r.callee.qualified_name) for r in self.edges()},
                         {('a','c'), ('b','c'), ('outer','outer.inner'), ('outer.inner','c')})

    def test_imports_qualified_alias_relative_and_reexports(self):
        self.write('app/__init__.py', 'from .auth import verify\n')
        self.write('app/auth.py', 'def verify(): pass\n')
        self.write('app/use.py', 'from .auth import verify as check\nfrom app import auth\n'
                   'import app.auth\nimport app.auth as a\nfrom app import verify\n'
                   'def use():\n check()\n auth.verify()\n app.auth.verify()\n a.verify()\n verify()\n')
        edges = self.edges()
        self.assertEqual(len(edges), 5)
        self.assertTrue(all(r.resolution == 'resolved' and r.callee.location.path == 'app/auth.py' for r in edges))

    def test_self_cls_and_class_namespaces(self):
        self.write('demo.py', 'def y(): pass\nclass A:\n def x(self):\n  self.y()\n  y()\n'
                   ' def y(self): pass\n @classmethod\n def c(cls): cls.y()\n'
                   ' @staticmethod\n def static(self): self.y()\n'
                   ' def keyword(*, self): self.y()\n def variadic(*self): self.y()\n')
        edges = self.edges()
        resolved = {(r.caller.qualified_name, r.callee.qualified_name) for r in edges if r.callee}
        self.assertEqual(resolved, {('A.x','A.y'), ('A.x','y'), ('A.c','A.y')})
        self.assertTrue(all(edge.resolution == 'unresolved' for edge in edges[-3:]))

    def test_ambiguous_conditional_import_never_picks_target(self):
        self.write('a.py', 'def foo(): pass')
        self.write('b.py', 'def foo(): pass')
        self.write('use.py', 'if enabled:\n from a import foo\nelse:\n from b import foo\ndef use(): foo()')
        edge = self.edges()[0]
        self.assertEqual(edge.resolution, 'ambiguous')
        self.assertIsNone(edge.callee)
        self.assertEqual(len(edge.candidates), 2)

    def test_dynamic_parameter_rebinding_and_unrelated_names(self):
        self.write('other.py', 'def callback(): pass')
        self.write('demo.py', 'def foo(): pass\ndef run(callback, obj, name):\n'
                   ' fn = getattr(obj, name)\n fn()\n callback()\n foo()\n foo = callback\n'
                   ' factory()[name]()\n')
        self.assertTrue(all(r.resolution == 'unresolved' for r in self.edges()))

    def test_import_cycle_and_import_target_edit(self):
        self.write('a.py', 'from b import foo\ndef use(): foo()')
        self.write('b.py', 'from a import foo')
        self.assertEqual(self.edges()[0].resolution, 'unresolved')
        self.write('b.py', 'def foo(): pass')
        self.assertEqual(self.edges()[0].resolution, 'resolved')

    def test_src_layout_and_duplicate_module_is_ambiguous(self):
        self.write('src/app/auth.py', 'def foo(): pass')
        self.write('use.py', 'from app.auth import foo\ndef use(): foo()')
        self.assertEqual(self.edges()[0].resolution, 'resolved')
        self.write('app/auth.py', 'def foo(): pass')
        self.assertEqual(self.edges()[0].resolution, 'ambiguous')

    def graph(self):
        return CallHierarchy(self.root, self.provider.refresh())

    def test_lookup_ambiguity_qualified_names_and_innermost_line(self):
        self.write('a.py', 'def same(): pass\nclass A:\n def same(self): pass\n')
        self.write('b.py', 'def same(): pass\n')
        graph = self.graph()
        self.assertEqual(len(graph.lookup('same')), 3)
        self.assertEqual(graph.lookup('A.same'), graph.lookup('a.py:3'))
        self.assertEqual(graph.lookup('missing'), [])
        with self.assertRaisesRegex(ValueError, 'outside'):
            graph.lookup('../outside.py:1')
        with self.assertRaisesRegex(ValueError, 'only Python'):
            graph.lookup('main.go:1')

    def test_entry_paths_main_test_cli_http(self):
        self.write('app.py', 'def main(): a()\ndef a(): b()\ndef b(): pass\n'
                   '@router.post("/login")\ndef login(): b()\n'
                   'if __name__ == "__main__":\n main()\n')
        self.write('test_app.py', 'from app import b\ndef test_b(): b()\n')
        self.write('pyproject.toml', '[project.scripts]\ndemo = "app:main"\n')
        graph = self.graph()
        target = graph.lookup('b')[0]
        paths = graph.to_entry(target).paths
        self.assertEqual({path.entry_kind for path in paths}, {'MAIN', 'TEST', 'CLI', 'HTTP'})
        self.assertIn(['main', 'a', 'b'], [[s.name for s in path.nodes] for path in paths])
        self.assertEqual({r.caller.name for r in graph.incoming(target)}, {'a', 'login', 'test_b'})
        self.assertEqual(graph.outgoing(graph.lookup('a')[0])[0].callee, target)

    def test_cycles_and_hard_path_limits(self):
        self.write('demo.py', 'def a(): b()\ndef b(): a()\ndef c(): a()\n')
        graph = self.graph()
        target = graph.lookup('a')[0]
        self.assertTrue(any(path.cycle for path in graph.to_entry(target).paths))
        self.assertTrue(graph.to_entry(target, max_depth=1).truncated)
        self.assertTrue(graph.to_entry(target, max_nodes=1).truncated)
        self.assertLessEqual(len(graph.to_entry(target, max_paths=1).paths), 1)

    def test_ambiguous_edges_visible_but_not_traversed(self):
        self.write('demo.py', 'if enabled:\n def c(): pass\nelse:\n def c(): pass\ndef a(): c()\n')
        graph = self.graph()
        target = graph.lookup('demo.py:2')[0]
        self.assertEqual(graph.incoming(target)[0].resolution, 'ambiguous')
        self.assertEqual(len(graph.to_entry(target).paths[0].nodes), 1)

    def test_preview_is_bounded_and_rejects_outside_paths(self):
        from devdash.trace.models import SymbolLocation
        self.write('demo.py', '\n'.join(f'# line {i}' for i in range(100)))
        self.assertLessEqual(len(self.provider.preview(SymbolLocation('demo.py', 50), 1000)), 21)
        with self.assertRaises(ValueError):
            self.provider.preview(SymbolLocation('../outside.py', 1))

    def test_pattern_capture_and_rebound_method_do_not_invent_targets(self):
        self.write('demo.py', 'def foo(): pass\ndef run(value):\n match value:\n  case {"foo": foo}: foo()\n'
                   'class A:\n def method(self): pass\n def run(self, callback):\n'
                   '  self.method = callback\n  self.method()\n')
        self.assertTrue(all(edge.resolution == 'unresolved' for edge in self.edges()))

    def test_encoding_cookie_invalid_encoding_deleted_and_permission_errors(self):
        from unittest.mock import patch
        latin = self.root/'latin.py'
        latin.write_bytes('# coding: latin-1\ndef café(): pass\n'.encode('latin-1'))
        (self.root/'invalid.py').write_bytes(b'def broken():\n \xff')
        index = self.provider.refresh()
        self.assertEqual(index.files_indexed, 1)
        self.assertEqual(len(index.warnings), 1)
        self.assertEqual(self.graph().lookup('café')[0].location.path, 'latin.py')
        self.write('blocked.py', 'def blocked(): pass')
        with patch('devdash.trace.python.read_source', side_effect=PermissionError):
            index = self.provider.refresh()
        self.assertTrue(any('blocked.py: PermissionError' in warning for warning in index.warnings))
        self.assertFalse(any(s.name == 'blocked' for s in index.symbols.values()))

    def test_file_ast_total_and_symbol_limits_are_visible(self):
        self.write('a.py', 'def a(): pass\n' * 10)
        for limits in (IndexLimits(max_file_bytes=10), IndexLimits(max_ast_nodes=5),
                       IndexLimits(max_total_bytes=10), IndexLimits(max_symbols=2)):
            with self.subTest(limits=limits):
                index = PythonAstProvider(self.root, limits).refresh()
                self.assertTrue(index.warnings)

    def test_large_cyclic_graph_has_bounded_paths_and_rendering(self):
        from devdash.trace.presentation import trace_data
        self.write('large.py', '\n'.join(f'def f{i}(): f{(i+1)%600}(); f0()' for i in range(600)))
        graph = self.graph()
        symbol = graph.lookup('f0')[0]
        paths = graph.to_entry(symbol, max_nodes=50, max_paths=10, max_depth=10)
        self.assertTrue(paths.truncated)
        self.assertLessEqual(paths.visited_nodes, 50)
        self.assertLessEqual(len(paths.paths), 10)
        data = trace_data(graph, 'f0', max_relations=20)
        self.assertTrue(data['truncated'])
        self.assertEqual(len(data['incoming']), 20)
