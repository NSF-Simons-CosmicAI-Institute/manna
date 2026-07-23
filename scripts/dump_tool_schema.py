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
from pathlib import Path

from fastmcp import Client

from astro_archives_mcp.app import build_mcp

SNAPSHOT_PATH = Path(__file__).resolve().parents[1] / "contracts" / "tool-schema.json"


async def build_snapshot() -> dict:
    """The tool surface as a JSON-stable dict: name, description, inputSchema."""
    async with Client(build_mcp()) as client:
        tools = await client.list_tools()
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
