"""End-to-end workflow: vo_target_resolve → vo_cone_search chain.

Simulates the LLM action:
    1. Call vo_target_resolve to get RA/Dec for a named object.
    2. Feed those coordinates directly into vo_cone_search.

Pins that the resolver → positional-query handoff works and that the
coordinates flow through correctly. ConeSearchClient is faked; no network.
"""

import pytest
from astropy.table import Table
from fastmcp import Client

from manna.tools import cone as cone_tools
from manna.tools import resolver as resolver_tools

SCS_ENDPOINT = "https://gaia.ari.uni-heidelberg.de/cone/gaiadr2?"

# M87 coordinates returned by a successful Sesame lookup
M87_RA = 187.70593
M87_DEC = 12.39112


class _FakeResolver:
    def resolve(self, name: str) -> tuple[float, float] | None:
        return M87_RA, M87_DEC


class _FakeConeClient:
    def __init__(self):
        self.last_endpoint: str | None = None
        self.last_ra: float | None = None
        self.last_dec: float | None = None
        self.last_radius: float | None = None

    def search(self, *, endpoint, ra, dec, radius_deg, maxrec):
        self.last_endpoint = endpoint
        self.last_ra = ra
        self.last_dec = dec
        self.last_radius = radius_deg
        return Table({"ra": [ra], "dec": [dec]})


@pytest.fixture
def fake_resolver(monkeypatch):
    monkeypatch.setattr(resolver_tools, "_get_resolver", lambda: _FakeResolver())


@pytest.fixture
def fake_cone(monkeypatch):
    client = _FakeConeClient()
    monkeypatch.setattr(cone_tools, "_get_cone", lambda: client)
    return client


@pytest.mark.asyncio
async def test_resolve_then_cone_search(mcp_server, fake_resolver, fake_cone):
    """Resolve a name to coordinates, then pass them to a cone search.
    Verify the coordinates flow from resolve output into the cone query."""
    async with Client(mcp_server) as client:
        # Step 1: resolve the target name
        resolve_result = await client.call_tool("vo_target_resolve", {"name": "M87"})
        rp = resolve_result.structured_content
        assert rp["resolved"] is True
        ra, dec = rp["ra"], rp["dec"]

        # Step 2: use the returned coords in a cone search
        cone_result = await client.call_tool(
            "vo_cone_search",
            {
                "endpoint": SCS_ENDPOINT,
                "ra": ra,
                "dec": dec,
                "radius_deg": 0.1,
            },
        )
        cp = cone_result.structured_content

    assert cp["row_count"] == 1, f"Expected 1 row from fake; got: {cp}"
    assert fake_cone.last_endpoint == SCS_ENDPOINT
    assert fake_cone.last_ra == pytest.approx(M87_RA)
    assert fake_cone.last_dec == pytest.approx(M87_DEC)
    assert fake_cone.last_radius == pytest.approx(0.1)
