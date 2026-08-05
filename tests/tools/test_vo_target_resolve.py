"""End-to-end tests for vo_target_resolve through an in-memory MCP client."""

import pytest
from fastmcp import Client

import manna.tools.resolver as resolver_mod


class _FakeResolver:
    def __init__(self, result):
        self._result = result

    def resolve(self, name: str):
        return self._result


@pytest.fixture
def patch_resolve_found(monkeypatch):
    monkeypatch.setattr(resolver_mod, "_get_resolver", lambda: _FakeResolver((187.70593, 12.39112)))


@pytest.fixture
def patch_resolve_not_found(monkeypatch):
    monkeypatch.setattr(resolver_mod, "_get_resolver", lambda: _FakeResolver(None))


@pytest.mark.asyncio
async def test_known_object_returns_ra_dec(mcp_server, patch_resolve_found):
    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_target_resolve", {"name": "M87"})
        payload = result.structured_content

    assert payload["resolved"] is True
    assert payload["name"] == "M87"
    assert abs(payload["ra"] - 187.70593) < 1e-4
    assert abs(payload["dec"] - 12.39112) < 1e-4
    assert payload["frame"] == "icrs"
    assert payload["unit"] == "deg"


@pytest.mark.asyncio
async def test_unknown_name_returns_resolved_false(mcp_server, patch_resolve_not_found):
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "vo_target_resolve",
            {"name": "XYZZY_NOT_A_REAL_OBJECT_99999"},
        )
        payload = result.structured_content

    assert payload["resolved"] is False
    assert payload["name"] == "XYZZY_NOT_A_REAL_OBJECT_99999"
    assert payload.keys() == {"resolved", "name", "message"}


@pytest.mark.asyncio
async def test_empty_name_returns_validation_error(mcp_server):
    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_target_resolve", {"name": ""})
        payload = result.structured_content

    assert payload["error_class"] == "validation_error"
    assert payload["retry_strategy"] == "fix_and_retry"


@pytest.mark.asyncio
async def test_whitespace_only_name_returns_validation_error(mcp_server):
    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_target_resolve", {"name": "   "})
        payload = result.structured_content

    assert payload["error_class"] == "validation_error"


@pytest.mark.asyncio
async def test_name_is_stripped_before_lookup(mcp_server, patch_resolve_found):
    """Leading/trailing whitespace is stripped; the stored name is clean."""
    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_target_resolve", {"name": "  M87  "})
        payload = result.structured_content

    assert payload["resolved"] is True
    assert payload["name"] == "M87"
