"""Archive registry: discovery, ordering, integrity, and selection.

Per-archive *content* assertions live in the sibling `test_<archive>.py`
files (so deleting an archive deletes its test). This file covers the loader
mechanics that are archive-agnostic.
"""

import pytest

from astro_archives_mcp.archives import _select, discover_archives, get_active_archives
from astro_archives_mcp.archives._model import Archive, Schema
from astro_archives_mcp.config import get_settings

# The archives physically shipped in this deployment. Order here is the expected
# (priority, short_name) order. Adding/removing an archive updates this list AND
# its own test_<name>.py — nothing else.
EXPECTED_ORDER = [
    "datalab",
    "alma",
    "nrao",
    "eso",
    "cadc",
    "gaia",
    "gaia_ari",
    "sdss",
]


@pytest.fixture
def clear_archive_caches():
    """Reset the settings + active-archive caches around a test that toggles env."""
    get_settings.cache_clear()
    get_active_archives.cache_clear()
    yield
    get_settings.cache_clear()
    get_active_archives.cache_clear()


# ---------- discovery ----------


def test_discover_finds_every_shipped_archive():
    names = [a.short_name for a in discover_archives()]
    assert names == EXPECTED_ORDER


def test_discover_orders_by_priority_then_name():
    archives = discover_archives()
    keys = [(a.priority, a.short_name) for a in archives]
    assert keys == sorted(keys)


def test_discovery_returns_archive_instances():
    for archive in discover_archives():
        assert isinstance(archive, Archive)


# ---------- full-set integrity ----------


def test_short_names_are_unique():
    names = [a.short_name for a in discover_archives()]
    assert len(names) == len(set(names))


def test_validate_archives_passes_on_the_full_shipped_set():
    # Raises on any integrity violation; a clean return is the assertion.
    _select.validate_archives(discover_archives())


def test_every_schema_belongs_to_its_owning_archive():
    for archive in discover_archives():
        for schema in archive.schemas:
            assert schema.archive == archive.short_name


def test_no_duplicate_archive_table_pairs():
    seen: set[tuple[str, str]] = set()
    for archive in discover_archives():
        for schema in archive.schemas:
            key = (schema.archive, schema.table)
            assert key not in seen, f"Duplicate Schema entry for {key}"
            seen.add(key)


def test_every_cross_ref_resolves_within_the_full_set():
    """Strict on the FULL shipped set. A subset deployment may legitimately
    dangle a cross_ref, so this is a full-set-only invariant."""
    by_pair = {(s.archive, s.table): s for a in discover_archives() for s in a.schemas}
    for archive in discover_archives():
        for schema in archive.schemas:
            for ref in schema.cross_refs:
                assert ref in by_pair, (
                    f"{(schema.archive, schema.table)}.cross_refs -> {ref} "
                    f"which is not a Schema in any shipped archive"
                )


# ---------- construction / validation catches developer errors ----------


def _archive(short_name, *, schemas=(), priority=100):
    return Archive(
        short_name=short_name,
        display_name=short_name,
        host_substrings=(),
        schemas=schemas,
        priority=priority,
    )


def test_validate_rejects_duplicate_short_names():
    with pytest.raises(ValueError, match="Duplicate archive short_name"):
        _select.validate_archives((_archive("x"), _archive("x")))


def test_archive_rejects_schema_archive_mismatch():
    # Enforced at construction by Archive.__post_init__, not by validate_archives.
    with pytest.raises(ValueError, match="must match the archive's short_name"):
        Archive(
            short_name="x",
            display_name="x",
            host_substrings=(),
            schemas=(Schema(archive="y", table="t"),),
        )


def test_validate_rejects_duplicate_table_pairs():
    dupe = _archive(
        "x",
        schemas=(Schema(archive="x", table="t"), Schema(archive="x", table="t")),
    )
    with pytest.raises(ValueError, match="Duplicate Schema entry"):
        _select.validate_archives((dupe,))


# ---------- parse_allow (pure) ----------


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("datalab", frozenset({"datalab"})),
        ("datalab,alma", frozenset({"datalab", "alma"})),
        (" datalab , ALMA ", frozenset({"datalab", "alma"})),
        ("datalab,,alma,", frozenset({"datalab", "alma"})),
    ],
)
def test_parse_allow(raw, expected):
    assert _select.parse_allow(raw) == expected


# ---------- select_archives (pure) ----------


def test_select_none_returns_all_sorted():
    archives = discover_archives()
    assert _select.select_archives(archives, allow=None) == archives


def test_select_narrows_to_allow_set():
    archives = discover_archives()
    selected = _select.select_archives(archives, allow=frozenset({"datalab", "alma"}))
    assert [a.short_name for a in selected] == ["datalab", "alma"]


def test_select_ignores_unknown_names(caplog):
    archives = discover_archives()
    selected = _select.select_archives(archives, allow=frozenset({"datalab", "bogus"}))
    assert [a.short_name for a in selected] == ["datalab"]
    assert "unknown archive" in caplog.text.lower()


def test_select_empty_result_is_allowed_and_warns(caplog):
    archives = discover_archives()
    selected = _select.select_archives(archives, allow=frozenset({"bogus"}))
    assert selected == ()
    assert "no archives" in caplog.text.lower()


# ---------- end-to-end runtime selection via STABLE_ARCHIVES ----------


def test_stable_archives_env_narrows_the_active_set(monkeypatch, clear_archive_caches):
    from astro_archives_mcp.archives.endpoints import active_archives
    from astro_archives_mcp.archives.knowledge import active_schema_kb, lookup_schema

    monkeypatch.setenv("STABLE_ARCHIVES", "datalab,alma")
    get_settings.cache_clear()
    get_active_archives.cache_clear()

    active = [a.short_name for a in active_archives()]
    assert active == ["datalab", "alma"]

    # Only the selected archives' schemas are visible.
    assert {s.archive for s in active_schema_kb()} == {"datalab", "alma"}
    # A deselected archive's curated schema is no longer found (but the
    # archive stays reachable via registry search — not exercised here).
    assert lookup_schema(archive="nrao", table="tap_schema.obscore") is None
    assert lookup_schema(archive="alma", table="ivoa.obscore") is not None


def test_default_active_set_matches_discovery(clear_archive_caches):
    # clear_archive_caches already reset both caches; no env change here.
    assert get_active_archives() == discover_archives()
