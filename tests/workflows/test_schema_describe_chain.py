"""End-to-end workflow: vo_schema_describe → vo_tap_query(async) chain.

Simulates the LLM action:
    1. Call vo_schema_describe to get the curated enum + async-required
       guidance for NRAO's obscore.
    2. Use the discovered instrument_name='GBT' value (exact case from
       the enum) in an async ADQL submit.

Pins that the KB → query handoff works and that the value flows
through correctly. TapClient is faked; no network.
"""

import pytest
from fastmcp import Client

from manna.tools import tap as tap_tools


class _FakeTapClient:
    def __init__(self):
        self.last_endpoint: str | None = None
        self.last_adql: str | None = None

    def submit_async(self, *, endpoint, adql, maxrec):
        self.last_endpoint = endpoint
        self.last_adql = adql
        return f"{endpoint}/async/chain-test"

    def load_job(self, job_url):
        class _J:
            phase = "EXECUTING"
            starttime = None
            endtime = None
            error_summary = None

        return _J()

    def abort_job(self, job_url):
        pass

    def query(self, *, endpoint, adql, maxrec):
        raise NotImplementedError("workflow test uses async only")


@pytest.fixture
def fake_tap(monkeypatch):
    client = _FakeTapClient()
    monkeypatch.setattr(tap_tools, "_get_tap", lambda: client)
    return client


@pytest.mark.asyncio
async def test_describe_then_async_query_with_enum_value(mcp_server, fake_tap):
    """Discover the GBT enum value, then submit an async ADQL using it.
    Verify the value flows into the bound query."""
    async with Client(mcp_server) as client:
        # Step 1: describe the table
        describe = await client.call_tool(
            "vo_schema_describe",
            {"archive": "nrao", "table": "tap_schema.obscore"},
        )
        dp = describe.structured_content
        assert dp["known"] is True
        gbt = dp["value_enums"]["instrument_name"][3]
        assert gbt == "GBT"

        # Step 2: bind the discovered value into an async query
        nrao_tap = "https://data-query.nrao.edu/tap"
        adql = (
            "SELECT TOP 1 obs_publisher_did "
            "FROM tap_schema.obscore "
            f"WHERE instrument_name = '{gbt}' "
            "AND 1 = CONTAINS(POINT('ICRS', s_ra, s_dec), "
            "CIRCLE('ICRS', 184.74, 47.30, 0.5))"
        )
        promotion = await client.call_tool(
            "vo_tap_query",
            {"endpoint": nrao_tap, "adql": adql, "mode": "async"},
        )
        prom = promotion.structured_content
        assert prom["mode"] == "async"

    # The discovered enum value reached the backend ADQL verbatim.
    assert fake_tap.last_endpoint == nrao_tap
    assert "instrument_name = 'GBT'" in fake_tap.last_adql
