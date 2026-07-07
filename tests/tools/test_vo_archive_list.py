"""End-to-end test for vo_archive_list through an in-memory MCP client.

Verifies that the curated KNOWN_ARCHIVES registry — particularly the
usage_notes — surfaces correctly to the LLM via the tool layer.
"""

import pytest
from fastmcp import Client


@pytest.mark.asyncio
async def test_vo_archive_list_returns_curated_set(mcp_server):
    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_archive_list", {})
        payload = result.structured_content

    assert "archives" in payload
    assert "count" in payload
    assert payload["count"] == len(payload["archives"])
    assert payload["count"] >= 8  # we have 8 well-known archives today

    # First entry should be DataLab (the canonical-example archive),
    # second should be ALMA (prioritized to the top of the well-known set).
    assert payload["archives"][0]["short_name"] == "datalab"
    assert payload["archives"][1]["short_name"] == "alma"


@pytest.mark.asyncio
async def test_vo_archive_list_nrao_entry_carries_async_usage_note(mcp_server):
    """The most operationally important note: NRAO needs mode='async'
    for data queries. If this regresses, the LLM falls back to the
    trial-and-error loop we built this tool to avoid."""
    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_archive_list", {})
        payload = result.structured_content

    nrao = next(a for a in payload["archives"] if a["short_name"] == "nrao")
    notes_joined = " ".join(nrao["usage_notes"]).lower()

    # Three load-bearing facts must reach the LLM:
    assert "async" in notes_joined, "NRAO note about mode='async' missing"
    assert "tap_schema.obscore" in notes_joined, "NRAO non-standard obscore location missing"
    assert "3c218" in notes_joined or "radio designation" in notes_joined, (
        "NRAO target-aliasing note missing — LLM will fail on 'Hydra-A' lookups"
    )


@pytest.mark.asyncio
async def test_vo_archive_list_serializes_tuple_fields_as_lists(mcp_server):
    """Tuples in the dataclass must come out as JSON-friendly lists."""
    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_archive_list", {})
        payload = result.structured_content

    for entry in payload["archives"]:
        assert isinstance(entry["host_substrings"], list)
        assert isinstance(entry["notable_tables"], list)
        assert isinstance(entry["usage_notes"], list)


@pytest.mark.asyncio
async def test_vo_archive_list_filter_by_short_name_returns_single_entry(mcp_server):
    """short_name filter narrows to one archive — the token-saving path
    once the agent knows which archive it wants."""
    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_archive_list", {"short_name": "nrao"})
        payload = result.structured_content

    assert payload["count"] == 1
    assert payload["archives"][0]["short_name"] == "nrao"


@pytest.mark.asyncio
async def test_vo_archive_list_short_name_is_case_insensitive(mcp_server):
    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_archive_list", {"short_name": "NRAO"})
        payload = result.structured_content

    assert payload["count"] == 1
    assert payload["archives"][0]["short_name"] == "nrao"


@pytest.mark.asyncio
async def test_vo_archive_list_unknown_short_name_returns_empty(mcp_server):
    """Unknown name soft-fails to an empty list, not an error."""
    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_archive_list", {"short_name": "does-not-exist"})
        payload = result.structured_content

    assert payload["count"] == 0
    assert payload["archives"] == []


@pytest.mark.asyncio
async def test_vo_archive_list_filter_by_waveband(mcp_server):
    """waveband filter returns only matching archives; 'radio' is NRAO-only."""
    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_archive_list", {"waveband": "radio"})
        payload = result.structured_content

    short_names = {a["short_name"] for a in payload["archives"]}
    assert short_names == {"nrao"}
    assert payload["count"] == len(payload["archives"])


@pytest.mark.asyncio
async def test_vo_archive_list_no_args_still_returns_full_set(mcp_server):
    """Backward compatibility: no arguments returns every known archive."""
    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_archive_list", {})
        payload = result.structured_content

    assert payload["count"] >= 8


@pytest.mark.asyncio
async def test_vo_archive_list_includes_capabilities_for_each_archive(mcp_server):
    """Every entry should at minimum identify itself by short_name +
    display_name and expose the protocol URL fields (even when None)."""
    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_archive_list", {})
        payload = result.structured_content

    required_keys = {
        "short_name",
        "display_name",
        "host_substrings",
        "tap_url",
        "sia_url",
        "scs_url",
        "waveband",
        "description",
        "notable_tables",
        "usage_notes",
    }
    for entry in payload["archives"]:
        assert required_keys.issubset(entry.keys()), (
            f"archive {entry.get('short_name')} missing keys: {required_keys - entry.keys()}"
        )
