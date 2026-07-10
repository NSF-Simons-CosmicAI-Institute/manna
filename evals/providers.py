"""Tool providers — the three arms of the Pillar-1 MCP-quality comparison.

Each provider exposes the same tiny interface (an async context manager giving
`tools` + `call`), so the agent loop in harness.py is arm-agnostic:

  * MCPToolProvider  — the full server: all vo_* tools + KB (the thing we sell).
  * RawTapToolProvider — one dumb `run_adql(endpoint, adql)` tool, no curation.
  * RawWebToolProvider — one `http_get(url)` tool; the model does everything itself.

Comparing full-MCP against the two raw arms quantifies the server's lift in
iterations / tokens / accuracy. The raw providers deliberately do NOT reuse the
server's shaping/async/error-taxonomy — that curation is exactly what's under test.
"""

from __future__ import annotations

import math
from typing import Any

from fastmcp import Client

from astro_archives_mcp.app import build_mcp
from evals.harness import _anthropic_tools, _result_payload

# Raw arms cap rows/bytes crudely (a naive agent has no result-shaping); the agent
# loop also caps what the model sees via MAX_TOOL_RESULT_CHARS.
_RAW_MAXREC = 2000
_RAW_ROWS_TO_MODEL = 100


def _cell(v: Any) -> Any:
    """Coerce an astropy/numpy cell to a JSON-friendly scalar."""
    try:
        import numpy as np

        if v is np.ma.masked:
            return None
    except Exception:
        pass
    if hasattr(v, "item"):
        try:
            v = v.item()
        except Exception:
            pass
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


class ToolProvider:
    """Async-context tool source: `.tools` (Anthropic schema) + `await .call()`."""

    label: str = "provider"
    tools: list[dict[str, Any]] = []

    async def __aenter__(self) -> ToolProvider:
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def call(self, name: str, args: dict[str, Any]) -> tuple[Any, bool]:
        raise NotImplementedError


class MCPToolProvider(ToolProvider):
    """The full astro-archives-mcp server (arm: 'mcp')."""

    label = "mcp"

    def __init__(self, *, inject_notes: bool = False, no_discovery: bool = False):
        self._inject_notes = inject_notes
        self._no_discovery = no_discovery
        self._client: Client | None = None

    async def __aenter__(self) -> MCPToolProvider:
        self._client = Client(build_mcp())
        await self._client.__aenter__()
        self.tools = _anthropic_tools(
            await self._client.list_tools(),
            inject_notes=self._inject_notes,
            no_discovery=self._no_discovery,
        )
        return self

    async def __aexit__(self, *exc) -> bool:
        if self._client is not None:
            await self._client.__aexit__(*exc)
        return False

    async def call(self, name: str, args: dict[str, Any]) -> tuple[Any, bool]:
        assert self._client is not None
        result = await self._client.call_tool(name, args, raise_on_error=False)
        return _result_payload(result)


class RawTapToolProvider(ToolProvider):
    """Raw TAP access, no curation (arm: 'raw_tap'). One dumb sync ADQL executor."""

    label = "raw_tap"
    tools = [
        {
            "name": "run_adql",
            "description": (
                "Execute an ADQL query synchronously against an IVOA TAP service and "
                "return the result rows. You must supply the full TAP base URL yourself "
                "and know the archive's tables/columns and quirks — there is no "
                "discovery, name resolution, or guidance."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "endpoint": {
                        "type": "string",
                        "description": "TAP base URL, e.g. https://example.org/tap",
                    },
                    "adql": {"type": "string", "description": "ADQL query text"},
                },
                "required": ["endpoint", "adql"],
            },
        }
    ]

    async def call(self, name: str, args: dict[str, Any]) -> tuple[Any, bool]:
        if name != "run_adql":
            return {"error": f"unknown tool: {name}"}, True
        import asyncio

        def _query() -> dict[str, Any]:
            from pyvo.dal import TAPService

            svc = TAPService(args["endpoint"])
            res = svc.search(args["adql"], maxrec=_RAW_MAXREC)
            table = res.to_table()
            cols = list(table.colnames)
            total = len(table)
            rows = [[_cell(row[c]) for c in cols] for row in table[:_RAW_ROWS_TO_MODEL]]
            out: dict[str, Any] = {"columns": cols, "rows": rows, "row_count": total}
            if total > _RAW_ROWS_TO_MODEL:
                out["note"] = f"showing first {_RAW_ROWS_TO_MODEL} of {total} rows"
            return out

        try:
            return await asyncio.to_thread(_query), False
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}, True


class RawWebToolProvider(ToolProvider):
    """Raw web access, no curation (arm: 'raw_web'). One HTTP GET tool."""

    label = "raw_web"
    tools = [
        {
            "name": "http_get",
            "description": (
                "Perform an HTTP GET and return the response text. Use for any archive "
                "or web request (service discovery, TAP, SIA, name resolution, ...). You "
                "must construct the URLs and parse the responses (VOTable/XML/JSON) "
                "yourself — there are no astronomy-specific helpers."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "Absolute URL"}},
                "required": ["url"],
            },
        }
    ]

    async def call(self, name: str, args: dict[str, Any]) -> tuple[Any, bool]:
        if name != "http_get":
            return {"error": f"unknown tool: {name}"}, True
        import httpx

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
                resp = await client.get(args["url"])
            text = resp.text[:200_000]
            return {"status": resp.status_code, "text": text}, resp.is_error
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}, True


def make_provider(
    arm: str, *, inject_notes: bool = False, no_discovery: bool = False
) -> ToolProvider:
    if arm == "mcp":
        return MCPToolProvider(inject_notes=inject_notes, no_discovery=no_discovery)
    if arm == "raw_tap":
        return RawTapToolProvider()
    if arm == "raw_web":
        return RawWebToolProvider()
    raise ValueError(f"unknown arm: {arm!r}")
