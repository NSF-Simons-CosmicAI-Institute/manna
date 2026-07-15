"""Ablation: run the server with its curated context stripped out.

The whole point of astro-archives-mcp (vs. handing a model raw pyvo) is the
curated knowledge: each archive's ``usage_notes`` and its per-table
``Schema`` entries. Tier 3 of
the eval quantifies that value by running the same trap tasks twice — once with
the context and once without — and comparing trap-avoidance rates.

We strip context *harness-side* rather than adding a flag to production
``build_mcp`` (see plan §10): the tools resolve their KB references from module
globals at call time, so swapping those globals inside a context manager gives a
clean, fully-reversible ablation with zero production-code risk. The patch point
is ``archives._endpoints.get_active_archives`` — the module global that
``active_archives()`` (and hence ``vo_archive_list``) resolves at call time.

Stripped:
  * ``vo_archive_list`` -> every archive keeps its endpoints/tables but loses
    ``usage_notes`` (the async routing, obscore-location, geometry warnings, ...).
  * ``vo_schema_describe`` -> always reports ``known: false`` (as if the table
    had no curated entry), forcing the model to fall back to live introspection.
"""

from __future__ import annotations

import dataclasses
from contextlib import contextmanager

from astro_archives_mcp.archives import _endpoints
from astro_archives_mcp.tools import schema as _schema_tool


@contextmanager
def ablated_context():
    """Temporarily blind the server to its curated usage_notes + schema KB.

    `vo_archive_list` resolves archives via `archives._endpoints.active_archives()`,
    which reads `get_active_archives` from the endpoints module globals at
    call time — so swapping that global swaps what the tool sees. The schema
    tool is blinded by forcing every lookup to miss. Restores on exit even if
    the body raises.
    """
    orig_get_active = _endpoints.get_active_archives
    orig_lookup = _schema_tool.lookup_schema
    stripped = tuple(dataclasses.replace(a, usage_notes=()) for a in orig_get_active())
    try:
        _endpoints.get_active_archives = lambda: stripped
        _schema_tool.lookup_schema = lambda *, archive, table: None
        yield
    finally:
        _endpoints.get_active_archives = orig_get_active
        _schema_tool.lookup_schema = orig_lookup


@contextmanager
def full_context():
    """No-op sibling of :func:`ablated_context` so the harness can treat the two
    conditions symmetrically."""
    yield
