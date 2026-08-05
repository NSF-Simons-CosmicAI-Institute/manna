"""Real-archive regression guard for vo_survey_target.

Exercises the REAL resolve + fan-out end-to-end against recorded HTTP. Scoped to
`wavebands=["millimeter"]` so exactly one countable archive (ALMA, sync) is
queried — keeping the cassette deterministic while still proving the aggregation
path (row shape + summary math) against a live service. The multi-archive and
async (NRAO) fan-out is non-deterministic and is smoke-checked out-of-band.

Re-record with:  uv run pytest --record-mode=once -k survey_target_live
"""

import pytest
from fastmcp import Client


@pytest.mark.vcr(
    match_on=["method", "scheme", "host", "port", "path", "query", "body"],
)
async def test_survey_millimeter_hits_alma_live(mcp_server):
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "vo_survey_target",
            {"target": "NGC 253", "radius_deg": 0.1, "wavebands": ["millimeter"]},
        )
    out = result.structured_content

    assert out["resolved"]["frame"] == "icrs"

    # Exactly the millimeter archive was surveyed.
    rows = out["archives"]
    assert [r["archive"] for r in rows] == ["alma"]
    alma = rows[0]
    assert alma["waveband"] == "millimeter"
    assert alma["table"] == "ivoa.obscore"
    assert alma["status"] == "ok"
    assert isinstance(alma["count"], int) and alma["count"] >= 0

    # Summary math is consistent with the single ok row.
    summary = out["summary"]
    assert summary["archives_queried"] == 1
    assert summary["errors"] == 0
    assert summary["pending"] == 0
    if alma["count"] > 0:
        assert summary["archives_with_data"] == 1
        assert summary["wavebands"] == ["millimeter"]
