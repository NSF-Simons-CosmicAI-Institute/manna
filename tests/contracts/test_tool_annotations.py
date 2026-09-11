"""Every tool must declare read-only + open/closed-world annotations."""

from fastmcp import Client

from manna.app import build_mcp

# Tools that only read the in-process archive notes (closed world); everything else
# hits live archive services (open world). describe_table left this set
# when it started fetching real column lists from tap_schema.columns.
_LOCAL_TOOLS = {"list_archives"}


async def test_all_tools_are_annotated_read_only():
    async with Client(build_mcp()) as client:
        tools = await client.list_tools()
        assert len(tools) == 15
        for t in tools:
            ann = t.annotations
            assert ann is not None, f"{t.name} missing annotations"
            if t.name == "abort_async_job":
                assert ann.readOnlyHint is False and ann.idempotentHint is True
                continue
            assert ann.readOnlyHint is True, f"{t.name} must be readOnlyHint"
            expected_open = t.name not in _LOCAL_TOOLS
            assert ann.openWorldHint is expected_open, t.name
