"""Dump the MCP tool contract (tools/list) to contracts/tool-schema.json.

The committed snapshot is the consumer-driven contract that cosmic-coder (and
any other client) tests against at a pinned server version. Regenerate after
any deliberate tool change and commit the diff in the same PR:

    uv run python scripts/dump_tool_schema.py

tests/contracts/test_tool_schema_snapshot.py fails whenever the live surface
and the committed snapshot drift.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from fastmcp import Client

from astro_archives_mcp.app import build_mcp
from astro_archives_mcp.archives import get_active_archives
from astro_archives_mcp.config import get_settings

SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / "contracts" / "tool-schema.json"

_ARCHIVES_ENV_VAR = "STABLE_ARCHIVES"
_ABLATE_CONTEXT_ENV_VAR = "STABLE_ABLATE_CONTEXT"


async def build_snapshot() -> dict:
    """The tool surface as a JSON-stable dict: name, description, inputSchema.

    Forces the full default archive surface regardless of the ambient
    environment: some tool descriptions (e.g. vo_tap_query) are composed
    from the *active archive set*, and a developer's local STABLE_ARCHIVES
    (or a stray .env picked up by pydantic-settings) would otherwise narrow
    it, silently generating a wrong (narrowed) contract. Similarly, an
    ablated context (STABLE_ABLATE_CONTEXT) strips curated knowledge from
    tool descriptions, which must always be full in the snapshot. A real
    environment variable beats `.env` in pydantic-settings, so setting them
    here to the desired defaults (empty archives => every archive active;
    "0" => full context) is enough to override any `.env` value; the
    lru_cache'd settings/archive-set accessors are cleared so the overrides
    actually take effect, and cleared again on the way out so this function
    has no lasting side effects on the process.
    """
    had_prior_archives = _ARCHIVES_ENV_VAR in os.environ
    prior_value_archives = os.environ.get(_ARCHIVES_ENV_VAR)
    os.environ[_ARCHIVES_ENV_VAR] = ""
    get_settings.cache_clear()
    get_active_archives.cache_clear()

    had_prior_ablate = _ABLATE_CONTEXT_ENV_VAR in os.environ
    prior_value_ablate = os.environ.get(_ABLATE_CONTEXT_ENV_VAR)
    os.environ[_ABLATE_CONTEXT_ENV_VAR] = "0"
    get_settings.cache_clear()

    try:
        async with Client(build_mcp()) as client:
            tools = await client.list_tools()
    finally:
        if had_prior_archives:
            os.environ[_ARCHIVES_ENV_VAR] = prior_value_archives  # type: ignore[assignment]
        else:
            os.environ.pop(_ARCHIVES_ENV_VAR, None)

        if had_prior_ablate:
            os.environ[_ABLATE_CONTEXT_ENV_VAR] = prior_value_ablate  # type: ignore[assignment]
        else:
            os.environ.pop(_ABLATE_CONTEXT_ENV_VAR, None)

        get_settings.cache_clear()
        get_active_archives.cache_clear()

    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.inputSchema,
            }
            for t in sorted(tools, key=lambda t: t.name)
        ]
    }


def main() -> int:
    snapshot = asyncio.run(build_snapshot())
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {SNAPSHOT_PATH} ({len(snapshot['tools'])} tools)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
