"""Ablation: run the server with its curated context stripped out.

The whole point of astro-archives-mcp (vs. handing a model raw pyvo) is the
curated knowledge: ``known_archives.usage_notes`` and ``schema_kb``. Tier 3 of
the eval quantifies that value by running the same trap tasks twice — once with
the context and once without — and comparing trap-avoidance rates.

We strip context *harness-side* rather than adding a flag to production
``build_mcp`` (see plan §10): the tools resolve their KB references from module
globals at call time, so swapping those globals inside a context manager gives a
clean, fully-reversible ablation with zero production-code risk.

Stripped:
  * ``vo_archive_list`` -> every archive keeps its endpoints/tables but loses
    ``usage_notes`` (the async routing, obscore-location, geometry warnings, ...).
  * ``vo_schema_describe`` -> always reports ``known: false`` (as if the table
    had no curated entry), forcing the model to fall back to live introspection.
"""

from __future__ import annotations

import dataclasses
from contextlib import contextmanager

from astro_archives_mcp.tools import archives as _archives_tool
from astro_archives_mcp.tools import schema as _schema_tool


def _strip_usage_notes(known_archives):
    """Return a copy of the KNOWN_ARCHIVES tuple with usage_notes emptied."""
    return tuple(dataclasses.replace(a, usage_notes=()) for a in known_archives)


@contextmanager
def ablated_context():
    """Temporarily blind the server to its curated usage_notes + schema_kb.

    Reversible and re-entrant-safe for the single-process eval harness. Restores
    the original module globals on exit even if the body raises.
    """
    orig_archives = _archives_tool.KNOWN_ARCHIVES
    orig_lookup = _schema_tool.lookup_schema
    try:
        _archives_tool.KNOWN_ARCHIVES = _strip_usage_notes(orig_archives)
        # Force every schema lookup to miss -> vo_schema_describe returns known:false.
        _schema_tool.lookup_schema = lambda *, archive, table: None
        yield
    finally:
        _archives_tool.KNOWN_ARCHIVES = orig_archives
        _schema_tool.lookup_schema = orig_lookup


@contextmanager
def full_context():
    """No-op sibling of :func:`ablated_context` so the harness can treat the two
    conditions symmetrically."""
    yield
