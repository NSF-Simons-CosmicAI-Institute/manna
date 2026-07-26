"""STABLE_ABLATE_CONTEXT — eval-only flag serving the KB-stripped tool surface.

The ablation arm of cosmic-coder's context-value evals runs the server in a
container with this flag set instead of monkeypatching server internals
in-process. Archives stay present and reachable (additive-never-gating); only
the curated *claims* disappear: usage_notes, per-table Schema entries, and the
vo_tap_query cheat-sheet derived from them.
"""

import pytest
from fastmcp import Client

from astro_archives_mcp.app import build_mcp
from astro_archives_mcp.archives import get_active_archives
from astro_archives_mcp.archives._traps import CHEATSHEET_HEADER
from astro_archives_mcp.config import get_settings


@pytest.fixture
def _ablated(monkeypatch):
    """Flag on, caches re-read; teardown restores the cached default view."""
    monkeypatch.setenv("STABLE_ABLATE_CONTEXT", "1")
    get_settings.cache_clear()
    get_active_archives.cache_clear()
    yield
    get_settings.cache_clear()
    get_active_archives.cache_clear()


def test_default_keeps_curated_claims():
    archives = get_active_archives()
    assert any(a.usage_notes for a in archives)
    assert any(a.schemas for a in archives)


def test_flag_strips_notes_and_schemas_but_keeps_archives(_ablated):
    archives = get_active_archives()
    assert archives, "ablation must never remove archives, only claims"
    assert all(not a.usage_notes for a in archives)
    assert all(not a.schemas for a in archives)


async def test_default_tap_description_has_cheatsheet():
    async with Client(build_mcp()) as client:
        tools = {t.name: t for t in await client.list_tools()}
    assert CHEATSHEET_HEADER in (tools["vo_tap_query"].description or "")


async def test_flag_removes_tap_cheatsheet(_ablated):
    async with Client(build_mcp()) as client:
        tools = {t.name: t for t in await client.list_tools()}
    assert CHEATSHEET_HEADER not in (tools["vo_tap_query"].description or "")
