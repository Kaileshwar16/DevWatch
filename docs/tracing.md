# Static call tracing design

`trace/models.py` defines provider-neutral, project-relative identities, source
locations, callsites, resolution states, entry labels and trace paths. `TraceProvider`
produces a `TraceIndex` and bounded source previews. `CallHierarchy` performs lookup,
adjacency queries and bounded breadth-first reverse walks. The CLI and Textual
screen share presentation data; neither implements language resolution.

`source.py` owns file discovery and bounded encoding-aware source reads. It reuses
DevDash's generated-directory exclusions and adds site-packages/generated/vendor.
It does not follow symlinks or enter nested repositories. It scans only the chosen
project boundary; Git tracked files are not required, so new untracked code works.

`python.py` parses with stdlib AST and records lexical scopes, import bindings,
definitions and callsites. `resolution.py` connects those records without imports,
execution, a language server or a type checker. Unknown bindings never fall back
to a same-named symbol elsewhere. Ambiguous bindings retain candidate identities;
incoming queries expose these as ambiguous and path walks omit them. Local method
reassignment, argument shadowing and match captures suppress confident resolution.
Class calls point to the class symbol; they do not synthesize constructor calls.

`entries.py` labels direct calls from main guards, test-name/file conventions,
root `[project.scripts]`, and literal `app`/`router` route decorators. These are
possible entry points. A graph leaf is UNKNOWN. Files which cannot parse are
reported and omitted. Source changes invalidate only that file's parse record;
cross-file resolution is rebuilt to prevent stale import targets. Cache signatures
include nanosecond mtime/ctime, size and inode. Caches are per provider/session,
in memory only. The TUI refreshes explicitly with r and when the screen reopens.

Graph traversal has independent depth/path/node budgets. Source limits and
ambiguous-candidate budgets prevent large source/graph inputs from growing without
bound. Defaults favor an interactive inspection, and all truncation is surfaced.
`python -m scripts.benchmark_trace . /path/to/python/repository` measures initial
indexing, cached refresh, and caller/callee/path queries without running that code.

## Local measurements

Measured on Linux x86_64, Python 3.12.13, on 2026-09-16 with
`python -m scripts.benchmark_trace . /home/kailesh/scrapy`:

| Repository | Files | Symbols | Resolved edges | Initial index | Cached refresh | Median query |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DevWatch | 72 | 593 | 815 | 208.743 ms | 26.588 ms | 0.130 ms |
| Local Scrapy checkout | 439 | 6,906 | 5,936 | 1,824.709 ms | 199.126 ms | 0.121 ms |

These are single local runs, not cross-platform guarantees. Symbol counts include
module scopes. Queries sample the first 100 functions/methods and combine lookup,
incoming/outgoing adjacency and bounded entry-path search; they exclude rendering
and serialization. Maximum sampled query times were 0.316 ms and 0.258 ms.
Both refreshes reparsed zero files and both indexes had no warnings or truncation.
Scrapy additionally had 196 ambiguous calls; unresolved/external call records are
not counted as resolved edges. The UI indexes and queries on worker threads.

## Integration and future providers

An affected-check feature can join changed paths/line ranges against `SymbolLocation`
and pass a symbol's `file:line` identity to `CallHierarchy.lookup`. It need not import
the CLI or UI. This version deliberately leaves affected-check selection unchanged.

Future LSP adapters for pyright, gopls, rust-analyzer, clangd or TypeScript can implement
the same provider contract, preserving server evidence and ambiguous edges rather
than pretending all languages follow Python semantics. No LSP process is started
by this version.

Future runtime tracing must have a separate opt-in provider and explicit execution
authorization. It could ingest Python profiler/sys.settrace events, pytest results
and traceback locations. Observations would add run IDs, timestamps and observed
edges to a distinct result type with `evidence=runtime`; the UI must label these
“Observed runtime path” and never merge them silently with “Possible static path”.
Static indexes can correlate source locations with those observations, but cannot
establish which path executed. No instrumentation is implemented here.
