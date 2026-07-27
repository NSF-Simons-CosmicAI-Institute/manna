"""Tests for the archives._knowledge helpers over the archive registry.

Per-table *content* (ALMA obscore enums, datalab Q3C, NRAO missing columns)
is asserted per-archive in `tests/archives/test_<archive>.py`. This file covers
the `Schema` dataclass, the `lookup_schema` contract, and the integrity of the
aggregated `active_schema_kb()` view.
"""

import pytest

from manna.archives._endpoints import active_archives
from manna.archives._knowledge import (
    active_schema_kb,
    lookup_schema,
)
from manna.archives._model import Schema

# ---------- Schema dataclass ----------


def test_schema_is_frozen():
    s = Schema(archive="nrao", table="tap_schema.obscore")
    with pytest.raises(AttributeError):  # FrozenInstanceError is a subclass
        s.archive = "mutated"  # type: ignore[misc]


def test_schema_cross_refs_is_nested_tuple_shape():
    s = Schema(
        archive="nrao",
        table="tap_schema.obscore",
        cross_refs=(("alma", "ivoa.obscore"),),
    )
    assert s.cross_refs == (("alma", "ivoa.obscore"),)


# ---------- lookup ----------


def test_lookup_schema_finds_known_entry():
    s = lookup_schema(archive="nrao", table="tap_schema.obscore")
    assert s is not None
    assert s.archive == "nrao"
    assert s.table == "tap_schema.obscore"


def test_lookup_schema_returns_none_for_unknown_pair():
    assert lookup_schema(archive="bogus", table="bogus") is None


def test_lookup_schema_is_case_sensitive():
    assert lookup_schema(archive="NRAO", table="tap_schema.obscore") is None
    assert lookup_schema(archive="nrao", table="TAP_SCHEMA.OBSCORE") is None


# ---------- active_schema_kb() view integrity ----------


def test_every_schema_archive_is_a_known_archive_short_name():
    valid_short_names = {a.short_name for a in active_archives()}
    for s in active_schema_kb():
        assert s.archive in valid_short_names, (
            f"Schema entry archive={s.archive!r} is not a known archive "
            f"short_name. Available: {sorted(valid_short_names)}"
        )


def test_no_two_schemas_share_an_archive_table_pair():
    seen: set[tuple[str, str]] = set()
    for s in active_schema_kb():
        key = (s.archive, s.table)
        assert key not in seen, f"Duplicate Schema entry for {key}; collapse the duplicates"
        seen.add(key)


def test_every_cross_ref_resolves_to_another_schema_entry():
    """Holds for the full shipped set (the default test deployment)."""
    by_pair = {(s.archive, s.table): s for s in active_schema_kb()}
    for s in active_schema_kb():
        for archive, table in s.cross_refs:
            assert (archive, table) in by_pair, (
                f"Schema({s.archive}, {s.table}).cross_refs references "
                f"{(archive, table)} but no such entry exists in the schema KB"
            )
