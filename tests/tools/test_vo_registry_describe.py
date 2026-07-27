import pytest
from fastmcp import Client

from manna.errors import ValidationError
from manna.tools import registry as ivoa_tools


@pytest.mark.vcr
async def test_vo_registry_describe_by_ivoid_via_in_memory_client(mcp_server):
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "vo_registry_describe",
            {"ivoid_or_url": "ivo://eso.org/tap_obs"},
        )
        payload = result.structured_content
        assert payload["ivoid"] == "ivo://eso.org/tap_obs"
        assert "tap" in payload["capabilities"]
        assert isinstance(payload["tables"], list)


class _FakeRegistry:
    def __init__(self, exc=None, described=None):
        self._exc = exc
        self._described = described or {}

    def describe(self, **_):
        if self._exc:
            raise self._exc
        return self._described


def test_vo_registry_describe_validation_error(monkeypatch):
    monkeypatch.setattr(
        ivoa_tools,
        "_get_registry",
        lambda: _FakeRegistry(exc=ValidationError(message="bad input")),
    )
    out = ivoa_tools.vo_registry_describe(ivoid_or_url="garbage")
    assert out["error_class"] == "validation_error"
