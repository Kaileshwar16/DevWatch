"""Read-only trace index/query measurements: python -m scripts.benchmark_trace ROOT ..."""
import argparse
import json
import statistics
import time
from pathlib import Path

from devdash.trace.graph import CallHierarchy
from devdash.trace.python import PythonAstProvider


def measure(root):
    provider = PythonAstProvider(root)
    index = provider.refresh()
    graph = CallHierarchy(root, index)
    symbols = [s for s in index.symbols.values() if s.kind in ('function', 'method')]
    queries = []
    for symbol in symbols[:100]:
        started = time.perf_counter()
        graph.lookup(f'{symbol.location.path}:{symbol.location.line}')
        graph.incoming(symbol)
        graph.outgoing(symbol)
        graph.to_entry(symbol)
        queries.append((time.perf_counter() - started) * 1000)
    refreshed = provider.refresh()
    return {'root': str(root), 'files': index.files_indexed, 'symbols': len(index.symbols),
            'calls': len(index.relations), 'resolved_edges': sum(r.resolution == 'resolved' for r in index.relations),
            'ambiguous_calls': sum(r.resolution == 'ambiguous' for r in index.relations),
            'initial_index_ms': round(index.index_ms, 3), 'refresh_ms': round(refreshed.index_ms, 3),
            'files_reparsed': refreshed.files_parsed,
            'median_query_ms': round(statistics.median(queries), 3) if queries else None,
            'max_query_ms': round(max(queries), 3) if queries else None,
            'warnings': len(index.warnings), 'truncated': index.truncated}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('roots', type=Path, nargs='+')
    for root in parser.parse_args().roots:
        print(json.dumps(measure(root.resolve())))
