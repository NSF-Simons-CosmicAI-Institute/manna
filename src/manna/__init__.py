from importlib.metadata import version as _pkg_version

# Single source of truth is pyproject.toml's version (via installed metadata) —
# a hardcoded string here shipped v0.6.0 whose /health still claimed 0.5.0.
__version__ = _pkg_version("manna-mcp")
