"""Temporary guard test for the notes-become-Note flip (task 3).

Verifies the coordinated flip: `Archive.usage_notes` holds `Note` objects at
the dataclass layer, while the `vo_archive_list` envelope still renders them
as plain strings (the LLM-facing contract is frozen) with no `audit` leak.
"""

import pytest
from fastmcp import Client

from astro_archives_mcp.archives._model import Note
from astro_archives_mcp.archives.datalab import ARCHIVE


def test_usage_notes_are_note_objects():
    assert ARCHIVE.usage_notes  # non-empty
    assert all(isinstance(n, Note) for n in ARCHIVE.usage_notes)


@pytest.mark.asyncio
async def test_archive_list_envelope_still_list_of_strings(mcp_server):
    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_archive_list", {"short_name": "datalab"})
        payload = result.structured_content

    (entry,) = payload["archives"]
    assert isinstance(entry["usage_notes"], list)
    assert all(isinstance(s, str) for s in entry["usage_notes"])
    assert "audit" not in entry  # audit never leaks into the envelope
