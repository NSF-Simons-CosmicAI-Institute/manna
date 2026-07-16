"""Content assertions for the NRAO Science Data Archive."""

from astro_archives_mcp.archives.nrao import ARCHIVE

SCHEMAS = {s.table: s for s in ARCHIVE.schemas}


def test_entry_covers_full_instrument_suite():
    """NRAO's first-party archive serves multiple instruments; the entry
    should reflect that rather than being VLA-only."""
    assert "data.nrao" in ARCHIVE.host_substrings
    assert "data-query.nrao" in ARCHIVE.host_substrings
    for instrument in ("VLA", "VLBA", "GMVA", "GBT"):
        assert instrument in ARCHIVE.description, (
            f"NRAO description must mention {instrument}; got: {ARCHIVE.description}"
        )
    assert ARCHIVE.waveband == "radio"
    assert ARCHIVE.tap_url == "https://data-query.nrao.edu/tap"
    # Non-standard obscore location; pin it so a future contributor doesn't
    # silently "fix" it to ivoa.obscore.
    assert "tap_schema.obscore" in ARCHIVE.notable_tables


def test_usage_notes_capture_critical_gotchas():
    """The usage_notes are the agent-facing knowledge base; NRAO's must cover
    the friction we learned the hard way."""
    notes = " ".join(n.text for n in ARCHIVE.usage_notes).lower()
    assert "async" in notes
    assert "tap_schema.obscore" in notes
    assert "scan" in notes and "execution" in notes.replace("execute", "")
    # Target-name aliasing — Hydra-A -> 3C218 was the live-demo friction.
    assert "3c218" in notes


def test_obscore_schema_missing_columns_and_enums():
    obscore = SCHEMAS["tap_schema.obscore"]
    assert "dataproduct_subtype" in obscore.missing_standard_columns
    assert obscore.value_enums["instrument_name"] == ("EVLA", "VLA", "VLBA", "GBT")
    assert obscore.value_enums["facility_name"] == ("NRAO",)


def test_key_note_audits_have_expected_outcomes():
    notes = {n.id: n for n in ARCHIVE.usage_notes}
    assert notes["sync-5xx-on-obscore"].audit.expect == "error"
    assert notes["obscore-ivoa-absent"].audit.expect == "empty"


def test_lower_upper_note_is_probeable():
    notes = {n.id: n for n in ARCHIVE.usage_notes}
    assert notes["lower-upper-fail"].audit.expect == "error"
