import pytest
from astropy.table import Table
from pyvo.dal.exceptions import DALAccessError, DALQueryError

from astro_archives_mcp.backends import sia as sia_backend
from astro_archives_mcp.backends.sia import SiaClient
from astro_archives_mcp.errors import DalQueryError

SIA_ENDPOINT = "https://ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/sia"


@pytest.mark.vcr
def test_sia_returns_metadata_table_with_access_url():
    client = SiaClient()
    table = client.search(
        endpoint=SIA_ENDPOINT,
        ra=185.43,
        dec=-31.99,
        size_deg=0.05,
        band=None,
        fmt=None,
        maxrec=5,
    )
    cols = {c.lower() for c in table.colnames}
    # SIA2 results always include some form of access URL column
    assert any("access_url" in c or "access" in c for c in cols)
    assert len(table) <= 5


@pytest.mark.vcr
def test_sia_respects_maxrec_truncation():
    client = SiaClient()
    table = client.search(
        endpoint=SIA_ENDPOINT,
        ra=185.43,
        dec=-31.99,
        size_deg=0.2,
        band=None,
        fmt=None,
        maxrec=3,
    )
    assert len(table) <= 3


# ---------- SIA1 / SIA2 version dispatch (mocked pyvo, no network) ----------


def _fake_result(n_rows: int) -> object:
    table = Table({"access_url": ["u"] * n_rows, "ra": [1.0] * n_rows})

    class _R:
        def to_table(self) -> Table:
            return table

    return _R()


def _install_fakes(monkeypatch, *, v2=None, v1=None):
    """Patch the SIA2/SIA1 service classes; record calls into `seen`."""
    seen: list[str] = []

    def _factory(tag, behavior):
        class _Svc:
            def __init__(self, endpoint):
                self.endpoint = endpoint

            def search(self, **kwargs):
                seen.append(tag)
                if isinstance(behavior, Exception):
                    raise behavior
                _Svc.kwargs = kwargs
                return behavior

        return _Svc

    monkeypatch.setattr(sia_backend, "_SIA2Service", _factory("v2", v2))
    monkeypatch.setattr(sia_backend, "_SIA1Service", _factory("v1", v1))
    return seen


def test_version_2_uses_sia2_only(monkeypatch):
    seen = _install_fakes(monkeypatch, v2=_fake_result(2), v1=_fake_result(2))
    SiaClient().search(endpoint="https://x/sia", ra=1, dec=2, size_deg=0.1, version="2")
    assert seen == ["v2"]


def test_version_1_uses_sia1_with_size_not_radius(monkeypatch):
    seen = _install_fakes(monkeypatch, v2=_fake_result(2), v1=_fake_result(2))
    SiaClient().search(endpoint="https://x/sia", ra=1.0, dec=2.0, size_deg=0.1, version="1")
    assert seen == ["v1"]
    # SIA1 uses a 2-tuple POS + scalar SIZE, never a 3-tuple CIRCLE.
    assert sia_backend._SIA1Service.kwargs["pos"] == (1.0, 2.0)
    assert sia_backend._SIA1Service.kwargs["size"] == 0.1
    assert "maxrec" not in sia_backend._SIA1Service.kwargs


def test_auto_falls_back_to_sia1_on_access_error(monkeypatch):
    seen = _install_fakes(
        monkeypatch,
        v2=DALAccessError("no capabilities"),
        v1=_fake_result(2),
    )
    table = SiaClient().search(endpoint="https://x/sia", ra=1, dec=2, size_deg=0.1, version="auto")
    assert seen == ["v2", "v1"]  # tried SIA2, fell back to SIA1
    assert len(table) == 2


def test_auto_does_not_fall_back_on_query_error(monkeypatch):
    seen = _install_fakes(
        monkeypatch,
        v2=DALQueryError("bad query"),
        v1=_fake_result(2),
    )
    with pytest.raises(DalQueryError):
        SiaClient().search(endpoint="https://x/sia", ra=1, dec=2, size_deg=0.1, version="auto")
    assert seen == ["v2"]  # query error is a real SIA2 failure — no SIA1 retry


def test_maxrec_cap_enforced_locally(monkeypatch):
    _install_fakes(monkeypatch, v2=_fake_result(5))
    table = SiaClient().search(
        endpoint="https://x/sia", ra=1, dec=2, size_deg=0.1, maxrec=3, version="2"
    )
    assert len(table) == 3
