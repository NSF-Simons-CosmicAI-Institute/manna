"""Every tool that accepts a user-supplied URL must run it past the SSRF guard.

The guard module has its own unit tests; these assert the *wiring* — that each
entry point refuses an internal target and, critically, that it refuses it
BEFORE any HTTP client is reached.

`169.254.169.254` (cloud metadata) is an IP literal, so the guard never
resolves it and the offline-DNS fixture in tests/conftest.py cannot mask the
block.
"""

import pytest
from fastmcp import Client

from manna.tools import cone as cone_tools
from manna.tools import registry as registry_tools
from manna.tools import sia as sia_tools
from manna.tools import tap as tap_tools

METADATA_URL = "http://169.254.169.254/tap"
LOOPBACK_URL = "http://127.0.0.1:8000/tap"


class _ExplodingClient:
    """Any attribute access means the guard let a request through."""

    def __getattr__(self, name):
        def _boom(*args, **kwargs):
            raise AssertionError(f"SSRF guard bypassed: backend .{name}() was called")

        return _boom


@pytest.fixture(autouse=True)
def _no_backends_reachable(monkeypatch):
    for module in (tap_tools, cone_tools, sia_tools):
        monkeypatch.setattr(module, "_get_tap", lambda: _ExplodingClient(), raising=False)
        monkeypatch.setattr(module, "_get_cone", lambda: _ExplodingClient(), raising=False)
        monkeypatch.setattr(module, "_get_sia", lambda: _ExplodingClient(), raising=False)
    monkeypatch.setattr(registry_tools, "_get_registry", lambda: _ExplodingClient(), raising=False)


@pytest.mark.parametrize("url", [METADATA_URL, LOOPBACK_URL])
@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("vo_tap_query", {"adql": "SELECT 1"}),
        ("vo_cone_search", {"ra": 10.0, "dec": 20.0, "radius_deg": 0.1}),
        ("vo_sia_search", {"ra": 10.0, "dec": 20.0, "size_deg": 0.1}),
    ],
)
@pytest.mark.asyncio
async def test_endpoint_tools_refuse_internal_targets(mcp_server, tool, args, url):
    async with Client(mcp_server) as client:
        result = await client.call_tool(tool, {"endpoint": url, **args})
        payload = result.structured_content

    assert payload["error_class"] == "validation_error"
    assert payload["retry_strategy"] == "abandon"


@pytest.mark.parametrize("url", [METADATA_URL, LOOPBACK_URL])
@pytest.mark.asyncio
async def test_registry_describe_refuses_internal_url(mcp_server, url):
    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_registry_describe", {"ivoid_or_url": url})
        payload = result.structured_content

    assert payload["error_class"] == "validation_error"
    assert payload["retry_strategy"] == "abandon"


@pytest.mark.asyncio
async def test_registry_describe_still_accepts_an_ivoid(mcp_server):
    """An `ivo://` IVOID is not a fetch target — it is resolved via RegTAP.

    Guarding it would break the documented discovery path, so it must reach the
    backend (which here explodes, proving it got that far rather than being
    refused by the guard).
    """
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "vo_registry_describe", {"ivoid_or_url": "ivo://cadc.nrc.ca/tap"}
        )
        payload = result.structured_content

    assert payload["error_class"] == "internal_error"
