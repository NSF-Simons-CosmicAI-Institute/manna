"""Compose the FastMCP server and mount it under Starlette with health probes."""

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from manna import __version__
from manna.archives._pitfalls import upfront_note_cheatsheet
from manna.observability import (
    current_request_id,
    new_request_id,
)
from manna.tools import (
    abort_async_job,
    count_observations_near_target,
    describe_ivoa_service,
    describe_table,
    find_observations_of_target,
    get_async_job_results,
    get_async_job_status,
    list_archives,
    preview_table,
    resolve_target_name,
    run_adql_query,
    search_catalog_by_position,
    search_images_by_position,
    search_ivoa_registry,
    survey_archives_for_target,
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


# Closed-world: reads only the in-process archive notes. Open-world: hits live services.
_LOCAL = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
_REMOTE = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
# abort_async_job DELETEs an upstream UWS job — not read-only, but idempotent
# (deleting an already-gone job is a no-op) and destructive.
_ABORT = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
    openWorldHint=True,
)


def _tap_query_description() -> str:
    """run_adql_query's docstring + the derived cheatsheet of up-front notes.

    Derived here, at build time, rather than baked into the docstring: the blob
    depends on which archives are active (``MANNA_ARCHIVES``), and
    ``upfront_note_cheatsheet`` reads the ``lru_cache``d active set at call time.
    Empty cheatsheet (e.g. a selection with no tagged pitfalls) leaves the
    docstring untouched.
    """
    base = run_adql_query.__doc__ or ""
    cheatsheet = upfront_note_cheatsheet()
    return f"{base}\n\n{cheatsheet}" if cheatsheet else base


def build_mcp() -> FastMCP:
    """Construct the FastMCP server with all tools registered.

    Every tool is read-only (the server never mutates archive state) except
    ``abort_async_job``, which deletes an upstream UWS job. Tools that hit live
    archive services are open-world; list_archives is the one closed-world
    archive-notes reader (describe_table left that set when it grew a live column
    fetch).
    """
    # Pass version explicitly: FastMCP otherwise reports *its own* version in
    # the initialize handshake's serverInfo, so every client saw the FastMCP
    # release (e.g. "3.4.7") where MANNA's belongs. /health has always been
    # right; this makes the MCP seam agree with it.
    mcp = FastMCP(name="manna", version=__version__)
    mcp.tool(list_archives, annotations=_LOCAL)
    mcp.tool(run_adql_query, annotations=_REMOTE, description=_tap_query_description())
    mcp.tool(get_async_job_status, annotations=_REMOTE)
    mcp.tool(get_async_job_results, annotations=_REMOTE)
    mcp.tool(abort_async_job, annotations=_ABORT)
    mcp.tool(search_ivoa_registry, annotations=_REMOTE)
    mcp.tool(describe_ivoa_service, annotations=_REMOTE)
    mcp.tool(describe_table, annotations=_REMOTE)
    mcp.tool(resolve_target_name, annotations=_REMOTE)
    mcp.tool(search_catalog_by_position, annotations=_REMOTE)
    mcp.tool(search_images_by_position, annotations=_REMOTE)
    mcp.tool(find_observations_of_target, annotations=_REMOTE)
    mcp.tool(count_observations_near_target, annotations=_REMOTE)
    mcp.tool(preview_table, annotations=_REMOTE)
    mcp.tool(survey_archives_for_target, annotations=_REMOTE)
    return mcp


def build_app() -> Starlette:
    mcp = build_mcp()
    mcp_app = mcp.http_app(path="/")

    async def health(_request):
        # No per-job stats: the server keeps no job state to report on.
        return JSONResponse({"status": "ok", "version": __version__})

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
