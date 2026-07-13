"""Content assertions for the NOIRLab Astro Data Lab archive."""

from astro_archives_mcp.archives.datalab import ARCHIVE

SCHEMAS = {s.table: s for s in ARCHIVE.schemas}


def test_identity():
    assert ARCHIVE.short_name == "datalab"
    assert ARCHIVE.waveband == "optical"
    assert ARCHIVE.tap_url == "https://datalab.noirlab.edu/tap"
    assert "datalab.noirlab" in ARCHIVE.host_substrings


def test_usage_notes_cover_known_adql_quirks():
    """Data Lab doesn't translate ADQL geometric functions, and NSC bright
    sources carry blend flags — recurring patterns the LLM needs to know."""
    notes = " ".join(ARCHIVE.usage_notes).lower()
    # ADQL geometric-function gap: the verified-live remedy is Q3C.
    assert "bounding-box" in notes or "bounding box" in notes
    assert "q3c_radial_query" in notes
    # Image access is SIAv1 — vo_sia_search (SIA2) reaches it via fallback.
    assert "siav1" in notes or "sia1" in notes or "sia2" in notes
    # NSC blend flags on bright sources.
    assert "blend" in notes or "flags" in notes


def test_ships_the_curated_tables():
    assert set(SCHEMAS) == {"nsc_dr2.object", "smash_dr2.object", "tap_schema.tables"}


def test_nsc_schema_recommends_q3c():
    notes = " ".join(SCHEMAS["nsc_dr2.object"].notes).lower()
    assert "q3c_radial_query" in notes


def test_smash_schema_cross_refs_nsc():
    assert ("datalab", "nsc_dr2.object") in SCHEMAS["smash_dr2.object"].cross_refs
