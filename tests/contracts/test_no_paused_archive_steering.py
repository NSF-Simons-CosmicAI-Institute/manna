"""No tool text may steer the model at a paused archive.

nrao ships paused (archives/nrao.py::paused) because its TAP service is being
rebuilt and MANNA traffic was loading it. The tool descriptions and parameter
examples are what the model actually reads, so an example short_name of 'nrao'
or a mention of its host would undo the pause. This pins the registered
surface, not the source.

`almascience.nrao.edu` is ALMA's North American mirror and is allowed.
"""

import json
import re

import pytest
from fastmcp import Client

_ALLOWED_HOST = "almascience.nrao.edu"
_FORBIDDEN = re.compile(r"\bnrao\b", re.IGNORECASE)


@pytest.mark.asyncio
async def test_default_tool_surface_never_mentions_nrao(mcp_server):
    async with Client(mcp_server) as client:
        tools = await client.list_tools()

    offenders: list[str] = []
    for t in tools:
        surface = " ".join([t.name, t.description or "", json.dumps(t.inputSchema)])
        surface = surface.replace(_ALLOWED_HOST, "")
        if _FORBIDDEN.search(surface):
            offenders.append(t.name)
    assert not offenders, f"tool text still steers at the paused nrao archive: {offenders}"
