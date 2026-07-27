"""Content assertions for the ESO Science Archive."""

from manna.archives.eso import ARCHIVE


def test_identity():
    assert ARCHIVE.short_name == "eso"
    assert ARCHIVE.tap_url == "https://archive.eso.org/tap_obs"
    assert "archive.eso" in ARCHIVE.host_substrings
    assert ARCHIVE.waveband == "optical"


def test_no_curated_schemas_yet():
    assert ARCHIVE.schemas == ()


def test_obscore_note_audit():
    notes = {n.id: n for n in ARCHIVE.usage_notes}
    note = notes["obscore-mixedcase"]
    assert note.audit.expect == "ok"
    # The probe deliberately uses the lowercase spelling: it verifies the
    # note's claim that table-name case does NOT matter here.
    assert "ivoa.obscore" in note.audit.adql
