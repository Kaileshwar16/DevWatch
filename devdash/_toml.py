"""TOML support on every supported Python version."""

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

__all__ = ["tomllib"]
