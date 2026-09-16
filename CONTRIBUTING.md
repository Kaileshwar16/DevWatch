# Contributing

Use Python 3.10 or newer on Linux or macOS. From a checkout:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m ruff check .
python -m unittest discover -s tests -v
git diff --check
python -m build
python scripts/smoke_wheel.py dist/devdash-0.3.0-py3-none-any.whl
```

The wheel smoke test creates a new temporary virtual environment, installs only
the wheel and its declared dependencies, and invokes the installed CLI from a
separate temporary directory. It verifies that imports come from that environment.
Use `--wheelhouse /path/to/wheels` for an offline install. Do not validate a release
using only an editable installation.

## Architecture

- `commands.py`, `canonical.py`, `scopes.py`: static command discovery, provenance,
  bounded package scopes, and config precedence.
- `config.py`: the backward-compatible `.devdash.toml` schema and validation.
- `metadata.py`: bounded, stat-invalidated metadata reads and parse caching.
- `preflight.py`: read-only prerequisites, without imports of project modules.
- `outcomes.py`, `execution.py`: shared structured outcomes and preflight/execution.
- `runner.py`: subprocess lifetime, output bounds, signals, timeout and reaping.
- `tasks.py`: concurrent session tasks, duplicate prevention and affected batches.
- `changes.py`, `impact.py`: one Git change snapshot and explainable path matching.
- `detectors/`, `discovery.py`: environment collection and per-detector degradation.
- `doctor.py`, `diagnostics.py`: environment validation and safe diagnostics.
- `cli.py`, `app.py`, `screens/`, `widgets/`: adapters and presentation.
- `trace/`: bounded static source discovery, AST resolution, provider-neutral call
  hierarchy queries and presentation; `screens/trace.py` runs analysis off the UI loop.

## Detector rules

Discovery must have no intentional project side effects. Never run project scripts,
install dependencies, load `.env`, import project modules, or mutate Docker state.
Use bounded metadata reads, directory walks and subprocess timeouts. Avoid following
symlinks during package discovery. Surface failures through warnings/diagnostics;
one detector must not break unrelated panels. Run filesystem work and subprocess
queries outside Textual's event loop. Configuration wins over detected commands.

A nonzero exit does not prove that tests failed. Add a small classifier only when
there is positive evidence of an actual check failure. Unrecognized failures are
ERROR. Keep raw exit codes and the compatibility tuple runner APIs.

## Tests

Use temporary directories/repositories and local fixtures. Unit tests should not
fetch arbitrary repositories or install dependencies. Tests needing Node, Go,
Cargo or pytest skip when unavailable; CI's integration job supplies these tools.
`DEVDASH_LIVE_DOCKER=1 python -m unittest discover -s tests -p test_integration.py -v`
adds a read-only daemon/Compose smoke; it does not create containers or pull images.

Test cwd ownership, config precedence, preflight availability, output classification,
JSON additions, cache invalidation and degraded mode when adding a detector. For
runner changes, test immediate cancellation, startup cancellation, descendants,
timeouts and shutdown. For TUI changes use Textual's headless driver.

`python -m scripts.benchmark` measures five discovery/snapshot runs in this checkout
and a temporary 150-package repository. Report actual measurements and machine
conditions rather than promising performance from code inspection.

Open a focused issue or pull request describing behavior and validation. No commit
convention or extra approval ceremony is required.
