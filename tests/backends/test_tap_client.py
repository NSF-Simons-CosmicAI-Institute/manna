import pytest

from manna.backends.tap import TapClient
from manna.errors import DalQueryError

SMASH_TAP = "https://datalab.noirlab.edu/tap"
SAFE_ADQL = "SELECT TOP 3 ra, dec FROM smash_dr2.object WHERE ra BETWEEN 185 AND 185.01 ORDER BY ra"


@pytest.mark.vcr
def test_tap_client_returns_astropy_table():
    client = TapClient()
    table = client.query(endpoint=SMASH_TAP, adql=SAFE_ADQL, maxrec=10)
    assert "ra" in table.colnames
    assert "dec" in table.colnames
    assert len(table) <= 3


@pytest.mark.vcr
def test_tap_client_bad_adql_raises_tap_query_error():
    client = TapClient()
    with pytest.raises(DalQueryError) as exc:
        client.query(
            endpoint=SMASH_TAP,
            adql="SELECT garbage FROM nowhere",
            maxrec=10,
        )
    assert "tap_query_error" in str(exc.value.error_class)
