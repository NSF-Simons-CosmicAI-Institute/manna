"""Backend tests for ResolverClient — replays Sesame HTTP via vcrpy cassettes.

Record cassettes with:
    uv run pytest tests/backends/test_resolver_client.py --record-mode=once
"""

import pytest

from manna.backends.resolver import ResolverClient
from manna.errors import ArchiveError


@pytest.mark.vcr
def test_resolve_known_object_returns_coordinates():
    client = ResolverClient()
    result = client.resolve("M87")
    assert result is not None
    ra, dec = result
    # M87 is near (187.7, 12.4) — loose tolerance for catalog differences
    assert 186.0 < ra < 189.0
    assert 11.0 < dec < 14.0


@pytest.mark.vcr
def test_resolve_unknown_name_returns_none():
    client = ResolverClient()
    result = client.resolve("XYZZY_NOT_A_REAL_OBJECT_99999")
    assert result is None


def test_resolve_network_failure_raises_archive_error(monkeypatch):
    """OSError (e.g. connection refused) surfaces as ArchiveError, not NameResolveError."""

    def _boom(name, cache=False):
        raise OSError("connection refused")

    monkeypatch.setattr("astropy.coordinates.SkyCoord.from_name", _boom)

    client = ResolverClient()
    with pytest.raises(ArchiveError):
        client.resolve("M87")
