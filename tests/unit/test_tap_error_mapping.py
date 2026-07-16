"""Pure-unit mapping of pyvo DAL exceptions to project error types.

pyvo wraps a *read* timeout that happens while fetching/parsing the
response body in `DALFormatError` (its `.cause` carries the original
`requests` exception). That escaped the boundary as a redacted
internal_error, so `vo_tap_query` mode='auto' only auto-promoted on
connect timeouts. These tests pin the mapping:

  DALFormatError(cause=Timeout)  -> TimeoutArchiveError (query, the
                                    auto-promote discriminator)
                                 -> ArchiveError (submit_async)
  DALFormatError(cause=other)    -> ArchiveError (upstream problem,
                                    not our internal_error)

No network / cassettes — `pyvo.dal.TAPService` is monkeypatched.
"""

import pytest
import requests
from pyvo.dal.exceptions import DALFormatError

from astro_archives_mcp.backends.tap import TapClient
from astro_archives_mcp.errors import ArchiveError, TimeoutArchiveError

ENDPOINT = "https://data-query.nrao.edu/tap"
ADQL = "SELECT * FROM tap_schema.obscore"


class _FakeTAPService:
    """Stand-in for pyvo.dal.TAPService whose search/submit_job raise."""

    def __init__(self, *args, exc, **kwargs):
        self._exc = exc

    def search(self, *args, **kwargs):
        raise self._exc

    def submit_job(self, *args, **kwargs):
        raise self._exc


def _patch_tapservice(monkeypatch, exc):
    """Make pyvo.dal.TAPService(...) return a fake that raises `exc`."""
    monkeypatch.setattr(
        "astro_archives_mcp.backends.tap.pyvo.dal.TAPService",
        lambda *a, **k: _FakeTAPService(exc=exc),
    )


def _format_error(cause):
    """Construct a DALFormatError the way pyvo does on a read-timeout.

    pyvo calls `DALFormatError(cause=<original requests exc>, url=...)`
    and the original is retrievable on the `.cause` attribute.
    """
    return DALFormatError(cause=cause, url=ENDPOINT)


def test_query_read_timeout_maps_to_timeout_archive_error(monkeypatch):
    err = _format_error(requests.exceptions.ReadTimeout("read timed out"))
    _patch_tapservice(monkeypatch, err)

    with pytest.raises(TimeoutArchiveError) as exc_info:
        TapClient().query(endpoint=ENDPOINT, adql=ADQL)

    # Must be the concrete project type the auto-promote path branches on.
    assert isinstance(exc_info.value, TimeoutArchiveError)


def test_query_non_timeout_format_error_maps_to_archive_error(monkeypatch):
    err = _format_error(ValueError("malformed VOTable"))
    _patch_tapservice(monkeypatch, err)

    with pytest.raises(ArchiveError) as exc_info:
        TapClient().query(endpoint=ENDPOINT, adql=ADQL)

    # A genuine format problem is an upstream error, not a timeout.
    assert not isinstance(exc_info.value, TimeoutArchiveError)


def test_submit_async_read_timeout_maps_to_archive_error(monkeypatch):
    err = _format_error(requests.exceptions.ReadTimeout("read timed out"))
    _patch_tapservice(monkeypatch, err)

    with pytest.raises(ArchiveError) as exc_info:
        TapClient().submit_async(endpoint=ENDPOINT, adql=ADQL)

    # submit_async has no auto-promote path; a plain archive_error is right.
    assert isinstance(exc_info.value, ArchiveError)
