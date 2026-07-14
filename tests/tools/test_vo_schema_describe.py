"""End-to-end test for vo_schema_describe through an in-memory MCP client."""

import pytest
from fastmcp import Client


@pytest.mark.asyncio
async def test_known_entry_returns_envelope_with_curated_fields(mcp_server):
    """Pins the structured fields for the NRAO obscore entry so a regression
    in the seed data fails loudly."""
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "vo_schema_describe",
            {"archive": "nrao", "table": "tap_schema.obscore"},
        )
        payload = result.structured_content

    assert payload["known"] is True
    assert payload["archive"] == "nrao"
    assert payload["table"] == "tap_schema.obscore"
    assert "dataproduct_subtype" in payload["missing_standard_columns"]
    assert payload["value_enums"]["instrument_name"] == [
        "EVLA",
        "VLA",
        "VLBA",
        "GBT",
    ]
    assert payload["value_enums"]["facility_name"] == ["NRAO"]


@pytest.mark.asyncio
async def test_notes_are_plain_strings_with_no_audit_leak(mcp_server):
    """§7 envelope invariant: `notes` is a list[str] — Audit metadata must
    never leak into the LLM-facing payload."""
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "vo_schema_describe",
            {"archive": "nrao", "table": "tap_schema.obscore"},
        )
        payload = result.structured_content

    assert payload["known"] is True
    notes = payload["notes"]
    assert isinstance(notes, list)
    assert len(notes) > 0
    for note in notes:
        assert isinstance(note, str)
        assert not isinstance(note, dict)


@pytest.mark.asyncio
async def test_unknown_pair_returns_known_false_with_no_other_keys(mcp_server):
    """On miss, only known/archive/table appear — no other Schema fields."""
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "vo_schema_describe",
            {"archive": "bogus", "table": "bogus.bogus"},
        )
        payload = result.structured_content

    assert payload == {
        "known": False,
        "archive": "bogus",
        "table": "bogus.bogus",
    }


@pytest.mark.asyncio
async def test_empty_archive_returns_validation_error(mcp_server):
    """Empty input is a validation error, not a soft-miss."""
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "vo_schema_describe",
            {"archive": "", "table": "tap_schema.obscore"},
        )
        payload = result.structured_content

    assert payload["error_class"] == "validation_error"
    assert payload["retry_strategy"] == "fix_and_retry"
