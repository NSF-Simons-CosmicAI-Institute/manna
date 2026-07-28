"""Integration tests for ``build_app()``.

These exercise the Starlette wiring via ``httpx.ASGITransport`` so the
FastMCP lifespan, the request-id middleware, and the ``/mcp`` mount path are
all hit. The in-memory MCP client used by ``tests/tools/`` bypasses Starlette
entirely, which is why the lifespan bug originally slipped through review.

NOTE: ``httpx.ASGITransport`` does NOT run ASGI lifespan events on its own.
We drive ``app.router.lifespan_context(app)`` manually so FastMCP's
StreamableHTTPSessionManager task group is initialized before any request.
Without this, hitting ``/mcp`` raises
``RuntimeError(StreamableHTTPSessionManager task group was not initialized)``
— which is exactly the regression we are guarding against.
"""

import contextlib

import httpx

from manna import __version__
from manna.app import build_app


@contextlib.asynccontextmanager
async def _client_for(app):
    """Yield an httpx AsyncClient with the Starlette lifespan already started."""
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


async def test_health_endpoint_returns_version():
    app = build_app()
    async with _client_for(app) as client:
        r = await client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["version"] == __version__
        # The stateless server no longer reports a result byte-store.
        assert "store" not in data
        assert "job_store" in data


async def test_ready_endpoint():
    app = build_app()
    async with _client_for(app) as client:
        r = await client.get("/ready")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


async def test_mcp_endpoint_responds():
    """Verify FastMCP lifespan is propagated to the parent Starlette.

    Without ``lifespan=mcp_app.lifespan`` on the parent Starlette, hitting
    ``/mcp`` raises ``RuntimeError: StreamableHTTPSessionManager task group
    was not initialized`` — which surfaces as HTTP 500. We send a minimal
    request just to confirm the endpoint exists and is wired correctly; we
    are testing the integration, not the MCP protocol.
    """
    app = build_app()
    async with _client_for(app) as client:
        r = await client.post(
            "/mcp/",
            headers={"Accept": "application/json, text/event-stream"},
            json={},
            follow_redirects=True,
        )
        # Anything other than 500 means the lifespan worked. The MCP-spec
        # responses are 400/406/422 depending on FastMCP version.
        assert r.status_code != 500, f"got 500: body={r.text!r}"
        # Defensive: explicit allowed set so we notice if FastMCP starts
        # returning 200 for empty requests.
        assert r.status_code in (200, 400, 405, 406, 415, 422), r.text
