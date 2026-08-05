import pytest
from fastmcp import Client

from manna.errors import ArchiveError
from manna.tools import registry as ivoa_tools


@pytest.mark.vcr
async def test_vo_registry_search_via_in_memory_client(mcp_server):
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "vo_registry_search",
            {"keywords": ["magellanic"], "servicetype": "tap", "maxrec": 5},
        )
        payload = result.structured_content
        assert payload["truncated"] is False
        assert isinstance(payload["services"], list)
        assert payload["row_count"] >= 1
        first = payload["services"][0]
        for key in ("ivoid", "title", "tap_url", "sia_url"):
            assert key in first


class _FakeRegistry:
    def __init__(self, exc=None, services=None):
        self._exc = exc
        self._services = services or []

    def search(self, **_):
        if self._exc:
            raise self._exc
        return self._services


def test_vo_registry_search_archive_error_returns_payload(monkeypatch):
    monkeypatch.setattr(
        ivoa_tools,
        "_get_registry",
        lambda: _FakeRegistry(exc=ArchiveError(message="registry down")),
    )
    out = ivoa_tools.vo_registry_search(keywords=["x"], servicetype=None, waveband=None, maxrec=5)
    assert out["error_class"] == "archive_error"
    assert out["retry_strategy"] == "wait_and_retry"
