"""Offline regression tests for the eval ablation (evals/context.py).

The ablation must actually change what the real tools return — through the
in-memory MCP client, no network (vo_archive_list / vo_schema_describe read
local KBs only). Guards against KB-refactor drift (the 0.5.0 archives refactor
silently broke the previous patch target).
"""

from fastmcp import Client

from astro_archives_mcp.app import build_mcp
from evals.context import ablated_context


async def test_ablation_strips_and_restores_through_real_tools():
    async with Client(build_mcp()) as client:
        full = await client.call_tool("vo_archive_list", {"short_name": "nrao"})
        full_schema = await client.call_tool(
            "vo_schema_describe", {"archive": "nrao", "table": "tap_schema.obscore"}
        )
        assert len(full.structured_content["archives"][0]["usage_notes"]) > 0
        assert full_schema.structured_content["known"] is True

        with ablated_context():
            ab = await client.call_tool("vo_archive_list", {"short_name": "nrao"})
            ab_schema = await client.call_tool(
                "vo_schema_describe", {"archive": "nrao", "table": "tap_schema.obscore"}
            )
        assert ab.structured_content["archives"][0]["usage_notes"] == []
        assert ab_schema.structured_content["known"] is False

        after = await client.call_tool("vo_archive_list", {"short_name": "nrao"})
        assert len(after.structured_content["archives"][0]["usage_notes"]) > 0


def test_ablated_context_is_exception_safe():
    from astro_archives_mcp import known_archives

    orig = known_archives.get_active_archives
    try:
        with ablated_context():
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert known_archives.get_active_archives is orig
