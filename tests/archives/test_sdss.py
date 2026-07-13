"""Content assertions for the Sloan Digital Sky Survey."""

from astro_archives_mcp.archives.sdss import ARCHIVE


def test_identity():
    assert ARCHIVE.short_name == "sdss"
    assert ARCHIVE.waveband == "optical"
    assert "sdss.org" in ARCHIVE.host_substrings


def test_metadata_only_archive_has_no_endpoints_or_schemas():
    # SDSS is listed for labeling; no first-party endpoint is surfaced.
    assert ARCHIVE.tap_url is None
    assert ARCHIVE.sia_url is None
    assert ARCHIVE.scs_url is None
    assert ARCHIVE.schemas == ()
