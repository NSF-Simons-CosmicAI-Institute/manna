"""The harness's inject_notes axis after issue #57.

Injection is now a shipped server default, so the harness no longer ADDS a
cheatsheet — the ablation arm SUBTRACTS the server's. If stripping ever silently
no-ops, experiment (a)'s C cell stops being a control and the C->D delta
collapses to noise, so pin it.
"""

from __future__ import annotations

from dataclasses import dataclass

from astro_archives_mcp.archives._traps import loud_trap_guidance, silent_trap_cheatsheet
from evals.context import ablated_context
from evals.harness import _anthropic_tools


@dataclass
class _FakeTool:
    name: str
    description: str
    inputSchema: dict  # noqa: N815 — mirrors the MCP descriptor field name


def _tools():
    return [
        _FakeTool(
            "vo_tap_query",
            f"Run an ADQL query.\n\n{silent_trap_cheatsheet()}",
            {"type": "object"},
        ),
        _FakeTool("vo_archive_list", "List archives.", {"type": "object"}),
    ]


def _desc(out, name):
    return next(t["description"] for t in out if t["name"] == name)


def test_default_keeps_the_server_injected_cheatsheet():
    """Default must mirror production — the harness measures what we ship."""
    out = _anthropic_tools(_tools())
    assert "q3c_radial_query" in _desc(out, "vo_tap_query")


def test_ablation_strips_the_cheatsheet_but_keeps_the_tool_guidance():
    out = _anthropic_tools(_tools(), inject_notes=False)
    desc = _desc(out, "vo_tap_query")
    assert "q3c_radial_query" not in desc
    assert "COUNT(DISTINCT member_ous_uid)" not in desc
    # Only the blob goes — the tool's own description must survive.
    assert "Run an ADQL query." in desc


def test_stripping_leaves_other_tools_untouched():
    out = _anthropic_tools(_tools(), inject_notes=False)
    assert _desc(out, "vo_archive_list") == "List archives."


def test_no_discovery_withholds_the_curated_tools():
    names = {t["name"] for t in _anthropic_tools(_tools(), no_discovery=True)}
    assert "vo_archive_list" not in names
    assert "vo_tap_query" in names


# ---------- tier-3 ablation must strip BOTH channels ----------


def test_ablated_context_strips_both_trap_channels():
    """Traps are curated knowledge, so the tier-3 ablation has to take them away
    too — otherwise the 'without curated context' arm silently keeps the server's
    advantage and the with/without delta understates the ROI.

    This works because ablated_context() blanks usage_notes on the active set and
    _traps.py resolves through that same patched global. It is load-bearing and
    easy to break (e.g. by snapshotting traps at import), so pin it.
    """
    lower = "SELECT * FROM tap_schema.obscore WHERE LOWER(target_name) = 'm87'"
    assert silent_trap_cheatsheet() != ""
    assert loud_trap_guidance("nrao", lower) is not None

    with ablated_context():
        assert silent_trap_cheatsheet() == ""
        assert loud_trap_guidance("nrao", lower) is None

    # ...and restored on exit.
    assert silent_trap_cheatsheet() != ""
    assert loud_trap_guidance("nrao", lower) is not None
