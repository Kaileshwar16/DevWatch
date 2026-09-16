"""Trace subcommand dispatch, isolated from environment/task CLI modes."""
import argparse
import json
import sys
from pathlib import Path

from devdash.detectors.project import find_project_root
from devdash.trace.graph import CallHierarchy
from devdash.trace.presentation import format_trace, trace_data
from devdash.trace.python import PythonAstProvider


def bounded_number(maximum):
    def parse(value):
        try:
            number = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError(f'must be an integer from 1 to {maximum}') from None
        if not 1 <= number <= maximum:
            raise argparse.ArgumentTypeError(f'must be from 1 to {maximum}')
        return number
    return parse


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog='devdash trace', description='Explore possible static Python call relationships.')
    parser.add_argument('target', help='symbol, Class.method, or project-relative file.py:line')
    parser.add_argument('--root', type=Path, default=None, help='explicit project boundary (default: nearest project root)')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--outgoing', action='store_true', help='show possible callees')
    mode.add_argument('--to-entry', action='store_true', help='walk possible callers toward likely entry points')
    parser.add_argument('--json', action='store_true', help='emit a schema-version-1 static trace object')
    parser.add_argument('--max-depth', type=bounded_number(100), default=12)
    parser.add_argument('--max-paths', type=bounded_number(1000), default=30)
    parser.add_argument('--max-nodes', type=bounded_number(100000), default=2000)
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve() if args.root else find_project_root(Path.cwd())
        provider = PythonAstProvider(root)
        graph = CallHierarchy(root, provider.refresh())
        data = trace_data(graph, args.target, outgoing=args.outgoing, to_entry=args.to_entry,
                          max_depth=args.max_depth, max_paths=args.max_paths, max_nodes=args.max_nodes)
        print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else
              format_trace(data, outgoing=args.outgoing, to_entry=args.to_entry))
        return 1 if data['error'] else 0
    except (OSError, ValueError) as exc:
        if args.json:
            print(json.dumps({'schema_version': 1, 'kind': 'call_hierarchy', 'evidence': 'static', 'error': str(exc)}))
        else:
            print(f'devdash trace: {exc}', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 0
