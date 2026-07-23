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


async def test_snapshot_ignores_archive_narrowing(monkeypatch):
    """build_snapshot() must always reflect the full default archive surface.

    A developer's local STABLE_ARCHIVES (or a stray .env) narrows the active
    archive set, which changes vo_tap_query's composed description. If
    build_snapshot() picked that up, a narrowed local environment would
    silently regenerate a wrong (narrowed) contract. Snapshot generation must
    force the full archive surface regardless of the ambient environment.
    """
    from astro_archives_mcp.archives import get_active_archives
    from astro_archives_mcp.config import get_settings

    monkeypatch.setenv("STABLE_ARCHIVES", "datalab")
    get_settings.cache_clear()
    get_active_archives.cache_clear()
    try:
        narrowed = await build_snapshot()
    finally:
        get_settings.cache_clear()
        get_active_archives.cache_clear()

    committed = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert committed == narrowed, (
        "build_snapshot() picked up a narrowed STABLE_ARCHIVES from the "
        "ambient environment; it must always build the full default "
        "archive surface."
    )
