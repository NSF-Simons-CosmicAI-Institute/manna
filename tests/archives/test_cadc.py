"""Content assertions for the Canadian Astronomy Data Centre."""

from astro_archives_mcp.archives.cadc import ARCHIVE


def test_identity():
    assert ARCHIVE.short_name == "cadc"
    assert ARCHIVE.waveband == "multi"
    # CADC contributes two host substrings; both must be present.
    assert "cadc-ccda.hia-iha" in ARCHIVE.host_substrings
    assert "ws.cadc-ccda" in ARCHIVE.host_substrings
    assert ARCHIVE.sia_url == "https://ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/sia"


def test_usage_notes_cover_datalink_indirection():
    notes = " ".join(n.text for n in ARCHIVE.usage_notes).lower()
    assert "datalink" in notes
    assert "obs_collection" in notes
