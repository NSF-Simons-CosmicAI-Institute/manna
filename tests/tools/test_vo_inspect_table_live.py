"""Real-archive regression guard for vo_inspect_table.

Exercises the REAL TapClient end-to-end against recorded HTTP: the live column
list from tap_schema.columns AND the best-effort TOP-n sample, both against Data
Lab's nsc_dr2.object (sync, reliable). This is the one tool whose value depends
on two live calls to the SAME TAP path with different ADQL, so body matching is
required to keep the cassette from cross-matching the two requests.

The NRAO unfiltered-sample soft-fail (sample_status='error' while columns still
return) is load-dependent and is smoke-checked out-of-band, not frozen here.

Re-record with:  uv run pytest --record-mode=once -k inspect_table_live
"""

import pytest
from fastmcp import Client


@pytest.mark.vcr(
    match_on=["method", "scheme", "host", "port", "path", "query", "body"],
)
async def test_inspect_datalab_table_live(mcp_server):
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "vo_inspect_table",
            {"table": "nsc_dr2.object", "archive": "datalab", "sample_rows": 3},
        )
    out = result.structured_content

    assert out["archive"] == "datalab"
    assert out["table"] == "nsc_dr2.object"

    # Real column list came back (name + datatype), including ra/dec.
    cols = {c["name"] for c in out["columns"]}
    assert {"ra", "dec"} <= cols
    assert all("datatype" in c for c in out["columns"])

    # Best-effort sample succeeded on this reliable sync table.
    assert out["sample_status"] == "ok"
    assert 1 <= len(out["sample_rows"]) <= 3
    assert "ra" in out["sample_rows"][0]
