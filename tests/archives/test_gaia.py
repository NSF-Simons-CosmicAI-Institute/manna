"""Content assertions for the ESA Gaia + Gaia ARI Heidelberg archives."""

from manna.archives.gaia import ARCHIVE as GAIA
from manna.archives.gaia_ari import ARCHIVE as GAIA_ARI


def test_gaia_identity():
    assert GAIA.short_name == "gaia"
    assert GAIA.tap_url == "https://gea.esac.esa.int/tap-server/tap"
    assert "gea.esac.esa" in GAIA.host_substrings


def test_gaia_usage_notes_cover_release_schemas_and_source_id():
    notes = " ".join(n.text for n in GAIA.usage_notes).lower()
    assert "gaiadr3" in notes
    assert "source_id" in notes


def test_gaia_key_note_audit_expectations():
    notes = {n.id: n for n in GAIA.usage_notes}
    assert notes["dr3-default-table"].audit.expect == "ok"


def test_gaia_ari_is_scs_only():
    assert GAIA_ARI.short_name == "gaia_ari"
    assert GAIA_ARI.scs_url == "https://gaia.ari.uni-heidelberg.de/cone/gaiadr2?"
    assert GAIA_ARI.tap_url is None and GAIA_ARI.sia_url is None
