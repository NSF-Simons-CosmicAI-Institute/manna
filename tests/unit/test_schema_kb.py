"""Schema dataclass + SCHEMA_KB contract tests."""

import pytest

from astro_archives_mcp.known_archives import KNOWN_ARCHIVES
from astro_archives_mcp.schema_kb import (
    SCHEMA_KB,
    Schema,
    lookup_schema,
)

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


def test_lookup_schema_finds_alma_obscore():
    s = lookup_schema(archive="alma", table="ivoa.obscore")
    assert s is not None
    # Controlled vocabularies the LLM filters on (verified against live TAP).
    assert "scientific_category" in s.value_enums
    assert s.value_enums["data_rights"] == ("Public", "Proprietary")
    assert s.value_enums["science_observation"] == ("T", "F")
    # Cross-linked to NRAO's obscore (ALMA is mirrored at NRAO).
    assert ("nrao", "tap_schema.obscore") in s.cross_refs


def test_lookup_schema_finds_alma_source_catalogue():
    s = lookup_schema(archive="alma", table="sourcecatalogue.source_cone_search")
    assert s is not None
    notes_joined = " ".join(s.notes).lower()
    # The load-bearing surprise: s_ra_deg/s_dec_deg are nullable -> CONTAINS
    # on them errors; filter on m_ra/m_dec instead.
    assert "m_ra" in notes_joined and "m_dec" in notes_joined
    assert "null" in notes_joined
    assert ("alma", "ivoa.obscore") in s.cross_refs


def test_lookup_schema_returns_none_for_unknown_pair():
    assert lookup_schema(archive="bogus", table="bogus") is None


def test_lookup_schema_is_case_sensitive():
    assert lookup_schema(archive="NRAO", table="tap_schema.obscore") is None
    assert lookup_schema(archive="nrao", table="TAP_SCHEMA.OBSCORE") is None


# ---------- SCHEMA_KB integrity ----------


def test_every_schema_archive_is_a_known_archive_short_name():
    valid_short_names = {a.short_name for a in KNOWN_ARCHIVES}
    for s in SCHEMA_KB:
        assert s.archive in valid_short_names, (
            f"Schema entry archive={s.archive!r} is not a known archive "
            f"short_name. Available: {sorted(valid_short_names)}"
        )


def test_no_two_schemas_share_an_archive_table_pair():
    seen: set[tuple[str, str]] = set()
    for s in SCHEMA_KB:
        key = (s.archive, s.table)
        assert key not in seen, f"Duplicate Schema entry for {key}; collapse the duplicates"
        seen.add(key)


def test_every_cross_ref_resolves_to_another_schema_entry():
    by_pair = {(s.archive, s.table): s for s in SCHEMA_KB}
    for s in SCHEMA_KB:
        for archive, table in s.cross_refs:
            assert (archive, table) in by_pair, (
                f"Schema({s.archive}, {s.table}).cross_refs references "
                f"{(archive, table)} but no such entry exists in SCHEMA_KB"
            )
