"""Bounded, stat-invalidated manifest reads shared across detectors.

Only callers' known metadata files belong here; never pass .env files.
"""
import json
from functools import lru_cache
from pathlib import Path
from calltrail._toml import tomllib

MAX_METADATA_BYTES = 1024 * 1024


@lru_cache(maxsize=512)
def _read(path: str, mtime: int, ctime: int, size: int) -> str:
    with open(path, encoding='utf-8', errors='replace') as handle:
        text = handle.read(MAX_METADATA_BYTES + 1)
    if len(text) > MAX_METADATA_BYTES:
        raise ValueError('Metadata exceeds 1 MiB read limit')
    return text


def read_text(path: Path) -> str:
    stat = path.stat()
    if stat.st_size > MAX_METADATA_BYTES:
        raise ValueError('Metadata exceeds 1 MiB read limit')
    return _read(str(path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)


@lru_cache(maxsize=512)
def _json(text: str) -> dict:
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError('JSON manifest must contain an object')
    return value


def read_json(path: Path) -> dict:
    return _json(read_text(path))


@lru_cache(maxsize=512)
def _toml(text: str) -> dict:
    return tomllib.loads(text)


def read_toml(path: Path) -> dict:
    return _toml(read_text(path))
