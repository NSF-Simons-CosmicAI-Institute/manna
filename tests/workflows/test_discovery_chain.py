"""End-to-end workflow: vo_archive_list → pick archive → vo_tap_query.

The point of `vo_archive_list` is that the LLM calls it FIRST when
unfamiliar with an archive, then uses what it learned to compose the
right query. This file pins that intent:

- The list contains the archives we promise.
- For each TAP-having entry, the LLM can take the `tap_url` straight
  to `vo_tap_query` without further introspection.
- The NRAO usage_notes — the ones we hammered out in PRs #17 and #19 —
  surface verbatim, so the LLM sees the mode='async' guidance, the
  obscore-location warning, etc.

If a regression strips a load-bearing note out of NRAO/DataLab/CADC,
this file fails immediately.
"""

import pytest
from astropy.table import Table
from fastmcp import Client

from manna.tools import tap as tap_tools


class _FakeTapClient:
    def __init__(self):
        self.last_endpoint = None
        self.last_adql = None
        self._table = Table({"obs_publisher_did": ["x"]})

    def query(self, *, endpoint, adql, maxrec):
        self.last_endpoint = endpoint
        self.last_adql = adql
        return self._table

    def submit_async(self, *, endpoint, adql, maxrec):
        self.last_endpoint = endpoint
        self.last_adql = adql
        return f"{endpoint}/async/discovery-test"

    def load_job(self, job_url):
        class _J:
            phase = "EXECUTING"
            starttime = None
            endtime = None
            error_summary = None

        return _J()

    def abort_job(self, job_url):
        pass


@pytest.fixture
def fake_tap(monkeypatch):
    client = _FakeTapClient()
    monkeypatch.setattr(tap_tools, "_get_tap", lambda: client)
    return client


@pytest.mark.asyncio
async def test_archive_list_surfaces_the_archives_we_promise(mcp_server):
    """An LLM calling vo_archive_list before composing a query should
    see at least the well-known archives by short_name."""
    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_archive_list", {})
        payload = result.structured_content

    short_names = {a["short_name"] for a in payload["archives"]}
    must_include = {"datalab", "nrao", "alma", "cadc", "gaia"}
    missing = must_include - short_names
    assert not missing, f"vo_archive_list missing well-known archives: {missing}"


@pytest.mark.asyncio
async def test_archive_list_nrao_entry_carries_async_and_obscore_notes(mcp_server):
    """Pins the load-bearing usage_notes for the LLM:
    - mode='async' for data queries
    - tap_schema.obscore (non-standard) location
    - 3C218 (target naming)"""
    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_archive_list", {})
        payload = result.structured_content

    nrao = next(a for a in payload["archives"] if a["short_name"] == "nrao")
    notes_joined = " ".join(nrao["usage_notes"]).lower()
    assert "async" in notes_joined
    assert "tap_schema.obscore" in notes_joined
    assert "3c218" in notes_joined or "radio designation" in notes_joined


@pytest.mark.asyncio
async def test_chain_pick_tap_url_from_list_and_query(mcp_server, fake_tap):
    """Simulate the LLM action: get the list → pick NRAO's tap_url →
    submit a query against it. Verify the right URL flowed through."""
    async with Client(mcp_server) as client:
        listing = await client.call_tool("vo_archive_list", {})
        archives = listing.structured_content["archives"]
        nrao = next(a for a in archives if a["short_name"] == "nrao")
        nrao_url = nrao["tap_url"]
        assert nrao_url, "NRAO tap_url must be populated"

        # LLM heeds the usage_note and uses mode='async'
        promotion = await client.call_tool(
            "vo_tap_query",
            {
                "endpoint": nrao_url,
                "adql": "SELECT TOP 1 * FROM tap_schema.obscore",
                "mode": "async",
            },
        )
        prom = promotion.structured_content
        assert prom["mode"] == "async"
        assert prom["archive"] == "nrao"

    # Verify the backend actually saw the URL from the listing
    assert fake_tap.last_endpoint == nrao_url


@pytest.mark.asyncio
async def test_archive_list_datalink_recipe_present_for_cadc(mcp_server):
    """CADC's datalink follow-through recipe (C-01) must reach the LLM
    via usage_notes."""
    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_archive_list", {})
        archives = result.structured_content["archives"]

    cadc = next(a for a in archives if a["short_name"] == "cadc")
    notes_joined = " ".join(cadc["usage_notes"]).lower()
    assert "datalink" in notes_joined
    # The 4-step recipe should be discoverable: semantics='#this' is the
    # key string the LLM needs to know.
    assert "#this" in notes_joined or "semantics" in notes_joined


@pytest.mark.asyncio
async def test_archive_list_datalab_adql_geometry_warning_present(mcp_server):
    """DataLab's gotcha — ADQL geometric functions don't translate —
    must reach the LLM as a usage_note."""
    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_archive_list", {})
        archives = result.structured_content["archives"]

    dl = next(a for a in archives if a["short_name"] == "datalab")
    notes_joined = " ".join(dl["usage_notes"]).lower()
    assert "bounding-box" in notes_joined or "bounding box" in notes_joined
