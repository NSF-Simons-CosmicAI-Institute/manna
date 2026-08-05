"""No tool description may still speak of a `job_id`.

The async handoff is the most behaviourally fragile path in the server — small
local models follow the tool text literally, and PR #64 exists because they
abandoned completed jobs when the prose was merely descriptive. A leftover
`job_id` in a description would send a model looking for a field no tool
returns and no tool accepts.

Descriptions are what the model actually reads, so this is a contract, not
housekeeping.
"""

import pytest
from fastmcp import Client


@pytest.mark.asyncio
async def test_no_tool_description_mentions_job_id(mcp_server):
    async with Client(mcp_server) as client:
        tools = await client.list_tools()

    offenders = [t.name for t in tools if "job_id" in (t.description or "")]
    assert not offenders, f"tool descriptions still reference job_id: {offenders}"


@pytest.mark.asyncio
async def test_async_lifecycle_tools_take_a_job_url_parameter(mcp_server):
    async with Client(mcp_server) as client:
        tools = {t.name: t for t in await client.list_tools()}

    for name in ("vo_tap_status", "vo_tap_results", "vo_tap_abort"):
        props = tools[name].inputSchema["properties"]
        assert "job_url" in props, f"{name} does not accept job_url"
        assert "job_id" not in props, f"{name} still accepts job_id"
