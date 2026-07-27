"""Content assertions for the Canadian Astronomy Data Centre."""

from manna.archives.cadc import ARCHIVE


def test_identity():
    assert ARCHIVE.short_name == "cadc"
    assert ARCHIVE.waveband == "multi"
    # CADC contributes two host substrings; both must be present.
    assert "cadc-ccda.hia-iha" in ARCHIVE.host_substrings
    assert "ws.cadc-ccda" in ARCHIVE.host_substrings
    assert ARCHIVE.sia_url == "https://ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/sia"


def test_tap_is_served_at_argus():
    """The old /tap path 404s (verified 2026-07-15); TAP moved to /argus."""
    assert ARCHIVE.tap_url == "https://ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/argus"


def test_usage_notes_cover_datalink_indirection_and_collection_column():
    notes = " ".join(n.text for n in ARCHIVE.usage_notes).lower()
    assert "datalink" in notes
    # caom2.Observation filters by `collection`; obs_collection is the
    # ivoa.ObsCore view's name — the note must teach the distinction.
    assert "collection" in notes
    assert "ivoa.obscore" in notes


def test_key_note_audits_have_expected_outcomes():
    notes = {n.id: n for n in ARCHIVE.usage_notes}
    assert notes["tap-at-argus"].audit.expect == "ok"
    assert notes["collection-column"].audit.expect == "nonempty"
