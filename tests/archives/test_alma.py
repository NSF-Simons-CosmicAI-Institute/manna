"""Content assertions for the ALMA Science Archive."""

from astro_archives_mcp.archives.alma import ARCHIVE

SCHEMAS = {s.table: s for s in ARCHIVE.schemas}


def test_identity():
    assert ARCHIVE.short_name == "alma"
    assert ARCHIVE.display_name == "ALMA Science Archive"
    assert ARCHIVE.waveband == "millimeter"
    assert ARCHIVE.tap_url == "https://almascience.nrao.edu/tap"


def test_exposes_sia2_endpoint():
    """ALMA publishes a SIAv2 image-discovery service in addition to TAP."""
    assert ARCHIVE.sia_url == "https://almascience.nrao.edu/sia2"


def test_usage_notes_capture_critical_gotchas():
    """Verified-against-live facts: INTERSECTS on s_region, member_ous_uid is
    the dataset key, science_observation drops calibration scans, and ALMA
    exposes more than TAP (SIAv2 + DataLink)."""
    notes = " ".join(n.text for n in ARCHIVE.usage_notes).lower()
    assert "intersects" in notes and "s_region" in notes
    assert "member_ous_uid" in notes
    assert "science_observation" in notes
    assert "siav2" in notes or "sia2" in notes
    assert "datalink" in notes


def test_ships_the_curated_tables():
    assert set(SCHEMAS) == {"ivoa.obscore", "sourcecatalogue.source_cone_search"}


def test_obscore_schema_value_enums_and_cross_ref():
    obscore = SCHEMAS["ivoa.obscore"]
    assert "scientific_category" in obscore.value_enums
    assert obscore.value_enums["data_rights"] == ("Public", "Proprietary")
    assert obscore.value_enums["science_observation"] == ("T", "F")
    # Cross-linked to NRAO's obscore (ALMA is mirrored at NRAO).
    assert ("nrao", "tap_schema.obscore") in obscore.cross_refs


def test_source_catalogue_schema_flags_nullable_geometry():
    src = SCHEMAS["sourcecatalogue.source_cone_search"]
    notes = " ".join(n.text for n in src.notes).lower()
    assert "m_ra" in notes and "m_dec" in notes
    assert "null" in notes
    assert ("alma", "ivoa.obscore") in src.cross_refs


def test_spatial_note_audit_expects_ok():
    notes = {n.id: n for n in ARCHIVE.usage_notes}
    assert notes["sync-spatial-ok"].audit.expect == "ok"


def test_access_format_note_is_probeable():
    """The 9-char truncation ('applicati') was fixed upstream (verified
    2026-07-15) — the note now states the full MIME value and is probed."""
    notes = {n.id: n for n in ARCHIVE.usage_notes}
    assert "access-format-truncated" not in notes
    note = notes["access-format-datalink"]
    assert note.audit.expect == "nonempty"
    assert "content=datalink" in note.text
