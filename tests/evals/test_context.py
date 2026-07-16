"""Offline guard for the Tier-3 ablation (evals/context.py).

No network, no model. The ablation is how we measure whether the curated
knowledge helps at all — if it silently breaks, the headline metric silently
stops existing. It broke once already (705199e removed the module global it
patched) and nothing caught it. These tests are that catch.
"""

from __future__ import annotations

import pytest

from astro_archives_mcp.tools.archives import vo_archive_list
from astro_archives_mcp.tools.schema import vo_schema_describe
from evals.context import ablated_context, full_context


def test_full_context_keeps_usage_notes():
    with full_context():
        result = vo_archive_list(short_name="datalab")
    assert result["archives"][0]["usage_notes"]


def test_ablated_context_strips_usage_notes():
    with ablated_context():
        result = vo_archive_list(short_name="datalab")
    assert result["count"] == 1, "ablation removes notes, never the archive itself"
    assert result["archives"][0]["usage_notes"] == []


def test_ablated_context_strips_notes_from_every_archive():
    with ablated_context():
        result = vo_archive_list()
    assert result["count"] > 0
    for archive in result["archives"]:
        assert archive["usage_notes"] == []


def test_ablated_context_also_patches_the_hint_branch():
    """vo_archive_list calls active_archives() twice — the second builds the hint
    for a filter that matched nothing. Patching a captured result instead of the
    function would leave this path un-ablated and raise nothing."""
    with ablated_context():
        result = vo_archive_list(short_name="does-not-exist")
    assert result["count"] == 0
    assert "datalab" in result["hint"]


def test_ablated_context_forces_schema_miss():
    with ablated_context():
        result = vo_schema_describe(archive="datalab", table="nsc_dr2.object")
    assert result["known"] is False


def test_ablation_restores_on_normal_exit():
    before = vo_archive_list(short_name="datalab")["archives"][0]["usage_notes"]
    with ablated_context():
        pass
    after = vo_archive_list(short_name="datalab")["archives"][0]["usage_notes"]
    assert after == before and after


def test_ablation_restores_even_when_body_raises():
    before = vo_archive_list(short_name="datalab")["archives"][0]["usage_notes"]
    with pytest.raises(RuntimeError, match="boom"):
        with ablated_context():
            raise RuntimeError("boom")
    after = vo_archive_list(short_name="datalab")["archives"][0]["usage_notes"]
    assert after == before and after, "a raising body must not leave the server ablated"
