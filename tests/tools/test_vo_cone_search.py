import pytest
from astropy.table import Table as _Table
from fastmcp import Client

from manna._fingerprint import query_fingerprint as _qfp
from manna.errors import DalQueryError
from manna.tools import cone as ivoa_tools

SCS_ENDPOINT = "https://gaia.ari.uni-heidelberg.de/cone/gaiadr2?"


@pytest.mark.vcr
async def test_vo_cone_search_via_in_memory_client(mcp_server):
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "vo_cone_search",
            {
                "endpoint": SCS_ENDPOINT,
                "ra": 185.43,
                "dec": -31.99,
                "radius_deg": 0.01,
                "maxrec": 20,
            },
        )
        payload = result.structured_content
        assert payload["truncated"] is False
        # Heidelberg Gaia cone returns rows; LLM tool envelope contract:
        assert "rows" in payload
        assert "columns" in payload
        names = {c["name"].lower() for c in payload["columns"]}
        assert "ra" in names and "dec" in names


class _FakeCone:
    def __init__(self, exc):
        self._exc = exc

    def search(self, **_):
        raise self._exc


def test_vo_cone_search_error_path(monkeypatch):
    monkeypatch.setattr(
        ivoa_tools,
        "_get_cone",
        lambda: _FakeCone(exc=DalQueryError(message="bad cone request")),
    )
    out = ivoa_tools.vo_cone_search(
        endpoint=SCS_ENDPOINT,
        ra=185.0,
        dec=-31.0,
        radius_deg=0.1,
        maxrec=10,
    )
    assert out["error_class"] == "tap_query_error"


class _FakeConeTable:
    def search(self, **_):
        return _Table({"ra": [1.0], "dec": [2.0]})


def test_cone_envelope_carries_cache_fields(monkeypatch):
    monkeypatch.setattr(ivoa_tools, "_get_cone", lambda: _FakeConeTable())
    out = ivoa_tools.vo_cone_search(
        endpoint=SCS_ENDPOINT, ra=185.43, dec=-31.99, radius_deg=0.01, maxrec=20
    )
    identity = "ra=185.430000 dec=-31.990000 radius=0.010000"
    assert out["query_fingerprint"] == _qfp("cone", SCS_ENDPOINT, identity)
    assert identity in out["save_recipe"]["code"]  # catalog query column
