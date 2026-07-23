"""The committed tool-schema snapshot must match the live tool surface.

contracts/tool-schema.json is the consumer-driven contract: cosmic-coder (and
any other client) tests against it at a pinned server version. A deliberate
tool change must regenerate the snapshot in the same PR, so breaking changes
are loud and reviewable — never silent.
"""

import json

from scripts.dump_tool_schema import SNAPSHOT_PATH, build_snapshot


async def test_snapshot_matches_live_surface():
    assert SNAPSHOT_PATH.exists(), (
        "contracts/tool-schema.json missing — generate it: "
        "uv run python scripts/dump_tool_schema.py"
    )
    live = await build_snapshot()
    committed = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert committed == live, (
        "tool surface drifted from the committed contract snapshot; if the "
        "change is deliberate, regenerate and commit: "
        "uv run python scripts/dump_tool_schema.py"
    )
