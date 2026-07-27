import pytest

from manna.backends.cone import ConeSearchClient
from manna.errors import ArchiveError

SCS_ENDPOINT = "https://gaia.ari.uni-heidelberg.de/cone/gaiadr2?"


@pytest.mark.vcr
def test_cone_returns_astropy_table():
    client = ConeSearchClient()
    table = client.search(
        endpoint=SCS_ENDPOINT,
        ra=185.43,
        dec=-31.99,
        radius_deg=0.01,
        maxrec=20,
    )
    assert "ra" in {c.lower() for c in table.colnames}
    assert "dec" in {c.lower() for c in table.colnames}
    assert len(table) <= 20


@pytest.mark.vcr
def test_cone_unreachable_endpoint_raises_archive_error():
    client = ConeSearchClient()
    with pytest.raises(ArchiveError):
        client.search(
            endpoint="https://nonexistent-scs.example.invalid/scs",
            ra=0.0,
            dec=0.0,
            radius_deg=0.01,
            maxrec=5,
        )
