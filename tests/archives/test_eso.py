"""Content assertions for the ESO Science Archive."""

from astro_archives_mcp.archives.eso import ARCHIVE


def test_identity():
    assert ARCHIVE.short_name == "eso"
    assert ARCHIVE.tap_url == "https://archive.eso.org/tap_obs"
    assert "archive.eso" in ARCHIVE.host_substrings
    assert ARCHIVE.waveband == "optical"


def test_no_curated_schemas_yet():
    assert ARCHIVE.schemas == ()
