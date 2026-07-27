import pytest
from fastmcp import Client

from manna.errors import ArchiveError
from manna.tools import sia as ivoa_tools

SIA_ENDPOINT = "https://ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/sia"


@pytest.mark.vcr
async def test_vo_sia_search_via_in_memory_client(mcp_server):
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "vo_sia_search",
            {
                "endpoint": SIA_ENDPOINT,
                "ra": 185.43,
                "dec": -31.99,
                "size_deg": 0.05,
                "maxrec": 5,
            },
        )
        payload = result.structured_content
        assert payload["truncated"] is False
        # SIA returns image metadata with access URL columns
        col_names = {c["name"].lower() for c in payload["columns"]}
        assert any("access" in n for n in col_names)


class _FakeSia:
    def __init__(self, exc):
        self._exc = exc

    def search(self, **_):
        raise self._exc


def test_vo_sia_search_error_path(monkeypatch):
    monkeypatch.setattr(
        ivoa_tools,
        "_get_sia",
        lambda: _FakeSia(exc=ArchiveError(message="sia down")),
    )
    out = ivoa_tools.vo_sia_search(
        endpoint=SIA_ENDPOINT,
        ra=185.0,
        dec=-31.0,
        size_deg=0.05,
        band=None,
        fmt=None,
        maxrec=5,
    )
    assert out["error_class"] == "archive_error"
