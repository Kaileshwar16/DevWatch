"""Repeatable bounded discovery/refresh benchmark; no project commands execute."""
import asyncio
import json
from pathlib import Path
import statistics
import tempfile
import time
from devdash.commands import discover_commands
from devdash.config import DevDashConfig
from devdash.discovery import collect_project


async def measure(root):
    config = DevDashConfig()
    discovery, snapshots = [], []
    for _ in range(5):
        start = time.perf_counter()
        commands = discover_commands(root, config)
        discovery.append((time.perf_counter()-start)*1000)
        start = time.perf_counter()
        await collect_project(root, config, commands)
        snapshots.append((time.perf_counter()-start)*1000)
    return {'commands':len(commands), 'discovery_ms':discovery, 'snapshot_ms':snapshots,
            'median_discovery_ms':statistics.median(discovery), 'median_snapshot_ms':statistics.median(snapshots)}


async def main():
    print('checkout', json.dumps(await measure(Path.cwd())))
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for i in range(150):
            package = root/f'package{i}'
            package.mkdir()
            (package/'package.json').write_text(json.dumps({'scripts':{'test':'node --test','lint':'eslint .'}}))
            for j in range(20):
                (package/f'source{j}.js').touch()
        print('150 packages, 3000 source files', json.dumps(await measure(root)))


if __name__ == '__main__':
    asyncio.run(main())
