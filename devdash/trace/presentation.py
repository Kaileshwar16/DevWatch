"""Plain-text and JSON presentation shared by the CLI and Trace screen."""
from dataclasses import asdict, replace

from devdash.trace.models import SymbolRef

DISCLAIMER = 'Possible static relationships; not observed runtime execution.'


def label(symbol: SymbolRef) -> str:
    suffix = '()' if symbol.kind in ('function', 'method') else ''
    return f'{symbol.qualified_name}{suffix}'


def location(symbol: SymbolRef) -> str:
    return f'{symbol.location.path}:{symbol.location.line}'


def trace_data(graph, target: str, *, outgoing=False, to_entry=False, max_relations=1000, **limits) -> dict:
    index = graph.index
    data = {'schema_version': 1, 'kind': 'call_hierarchy', 'evidence': 'static',
            'notice': DISCLAIMER, 'target': target, 'symbol': None, 'candidates': [],
            'incoming': [], 'outgoing': [], 'paths': [], 'warnings': index.warnings,
            'truncated': index.truncated, 'error': '',
            'stats': {'files_indexed': index.files_indexed, 'files_parsed': index.files_parsed,
                      'symbols_indexed': len(index.symbols), 'calls': len(index.relations),
                      'resolved_edges': sum(r.resolution == 'resolved' for r in index.relations),
                      'index_ms': index.index_ms}}
    try:
        matches = graph.lookup(target)
    except ValueError as exc:
        data['error'] = str(exc)
        return data
    if not matches:
        data['error'] = 'Symbol not found' if index.files_indexed else 'No indexable Python files in this project'
    elif len(matches) > 1:
        data['error'] = f'Multiple symbols named {target}; specify file:line'
        data['candidates'] = [asdict(symbol) for symbol in matches[:max_relations]]
        data['truncated'] |= len(matches) > max_relations
    else:
        symbol = matches[0]
        data['symbol'] = asdict(symbol)
        if to_entry:
            paths = graph.to_entry(symbol, **limits)
            data['paths'] = [asdict(path) for path in paths.paths]
            data['truncated'] |= paths.truncated
            data['visited_nodes'] = paths.visited_nodes
        elif outgoing:
            edges = graph.outgoing(symbol)
            data['outgoing'] = [asdict(replace(edge, candidates=edge.candidates[:20])) for edge in edges[:max_relations]]
            data['truncated'] |= len(edges) > max_relations or any(len(edge.candidates) > 20 for edge in edges[:max_relations])
        else:
            edges = graph.incoming(symbol)
            data['incoming'] = [asdict(replace(edge, candidates=edge.candidates[:20])) for edge in edges[:max_relations]]
            data['truncated'] |= len(edges) > max_relations or any(len(edge.candidates) > 20 for edge in edges[:max_relations])
    return data


def format_trace(data: dict, *, outgoing=False, to_entry=False) -> str:
    def describe(symbol):
        suffix = '()' if symbol['kind'] in ('function', 'method') else ''
        return f"{symbol['qualified_name']}{suffix}", f"{symbol['location']['path']}:{symbol['location']['line']}"

    lines = [DISCLAIMER, '']
    if data['error']:
        lines.append(data['error'])
        for symbol in data['candidates']:
            name, place = describe(symbol)
            lines.append(f'  {name}  {place}')
    else:
        name, place = describe(data['symbol'])
        lines.extend(('Symbol', f'  {name}', f'  {place}', ''))
        if to_entry:
            lines.append('Possible static entry paths')
            for path in data['paths']:
                lines.append(f"\n[{path['entry_kind']}] {path['entry_label']}")
                for i, node in enumerate(path['nodes']):
                    name, place = describe(node)
                    lines.append(f"  {'→ ' if i else ''}{name}  {place}")
                if path['cycle']:
                    lines.append('  [cycle detected; traversal stopped]')
                if path['truncated']:
                    lines.append('  [depth limit reached]')
            lines.append('\nOnly resolved static edges are traversed. UNKNOWN is a graph boundary, not a proven entry point.')
        else:
            lines.append('Possible static callees' if outgoing else 'Possible static callers')
            relations = data['outgoing' if outgoing else 'incoming']
            if not relations:
                lines.append('  No indexed relationships found; dynamic/external calls may be missing.')
            for relation in relations:
                symbol = relation['callee'] if outgoing else relation['caller']
                if symbol:
                    name, place = describe(symbol)
                    lines.extend((f'  {name} [{relation["resolution"]}]', f'    {place}'))
                else:
                    lines.append(f'  {relation["expression"]} [{relation["resolution"]}]')
                    lines.append(f'    {relation["reason"]}')
                site = relation['callsite']
                lines.append(f'    callsite: {site["path"]}:{site["line"]}')
                for candidate in relation['candidates']:
                    name, place = describe(candidate)
                    lines.append(f'    possible target: {name}  {place}')
    if data['truncated']:
        lines.append('\n[Truncated by safety limits; results are incomplete]')
    if data['warnings']:
        lines.append('\nTrace available with warnings:')
        lines.extend('  ' + warning for warning in data['warnings'])
    return '\n'.join(lines)
