"""Compose the FastMCP server and mount it under Starlette with health probes."""

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from astro_archives_mcp import __version__, job_store
from astro_archives_mcp.observability import (
    current_request_id,
    new_request_id,
)
from astro_archives_mcp.tools import (
    vo_archive_list,
    vo_cone_search,
    vo_find_observations,
    vo_registry_describe,
    vo_registry_search,
    vo_schema_describe,
    vo_sia_search,
    vo_tap_abort,
    vo_tap_query,
    vo_tap_results,
    vo_tap_status,
    vo_target_resolve,
)


class RequestIdMiddleware:
    """Pure ASGI middleware: set ``current_request_id`` for the duration of an
    HTTP request.

    Implemented as pure ASGI (not ``BaseHTTPMiddleware``) so the streaming
    ``/mcp`` endpoint is not wrapped in an extra anyio task group and memory
    stream, which can interfere with ``StreamableHTTPSessionManager``.

    Tests using the in-memory FastMCP Client bypass this middleware entirely;
    tests using ``httpx.ASGITransport`` against ``build_app()`` do go through
    it.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        token = current_request_id.set(new_request_id())
        try:
            await self.app(scope, receive, send)
        finally:
            current_request_id.reset(token)


# Closed-world: reads only the in-process KB. Open-world: hits live services.
_LOCAL = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
_REMOTE = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
# vo_tap_abort DELETEs an upstream UWS job — not read-only, but idempotent
# (deleting an already-gone job is a no-op) and destructive.
_ABORT = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
    openWorldHint=True,
)


def build_mcp() -> FastMCP:
    """Construct the FastMCP server with all tools registered.

    Every tool is read-only (the server never mutates archive state) except
    ``vo_tap_abort``, which deletes an upstream UWS job. Tools that hit live
    archive services are open-world; vo_archive_list is the one closed-world
    KB reader (vo_schema_describe left that set when it grew a live column
    fetch).
    """
    mcp = FastMCP(name="astro-archives-mcp")
    mcp.tool(vo_archive_list, annotations=_LOCAL)
    mcp.tool(vo_tap_query, annotations=_REMOTE)
    mcp.tool(vo_tap_status, annotations=_REMOTE)
    mcp.tool(vo_tap_results, annotations=_REMOTE)
    mcp.tool(vo_tap_abort, annotations=_ABORT)
    mcp.tool(vo_registry_search, annotations=_REMOTE)
    mcp.tool(vo_registry_describe, annotations=_REMOTE)
    mcp.tool(vo_schema_describe, annotations=_REMOTE)
    mcp.tool(vo_target_resolve, annotations=_REMOTE)
    mcp.tool(vo_cone_search, annotations=_REMOTE)
    mcp.tool(vo_sia_search, annotations=_REMOTE)
    mcp.tool(vo_find_observations, annotations=_REMOTE)
    return mcp


def build_app() -> Starlette:
    mcp = build_mcp()
    mcp_app = mcp.http_app(path="/")

    async def health(_request):
        return JSONResponse(
            {
                "status": "ok",
                "version": __version__,
                "job_store": job_store.size_estimate(),
            }
        )

    async def ready(_request):
        # Slice A: no backend pre-warm. Later slices ping a known TAP endpoint.
        return JSONResponse({"status": "ok"})

    return Starlette(
        routes=[
            Route("/health", health),
            Route("/ready", ready),
            Mount("/mcp", app=mcp_app),
        ],
        middleware=[Middleware(RequestIdMiddleware)],
        lifespan=mcp_app.lifespan,
    )
