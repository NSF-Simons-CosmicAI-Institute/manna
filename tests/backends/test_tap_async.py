"""TapClient async methods: cassette-replay tests against ESO TAP_OBS.

The UWS lifecycle requires multiple HTTP roundtrips (POST /async, GET
/{job}, POST /{job}/phase, GET /{job}/results, DELETE /{job}). vcrpy
records all of them; replay is offline.

To re-record: uv run pytest tests/backends/test_tap_async.py -k <name>
--record-mode=once  (requires network).
"""

import pytest

from manna.backends.tap import TapClient

ESO_TAP = "https://archive.eso.org/tap_obs"
SHORT_ADQL = (
    "SELECT TOP 3 dp_id, instrument_name FROM ivoa.ObsCore "
    "WHERE instrument_name = 'FORS2' ORDER BY dp_id"
)


@pytest.mark.vcr
def test_submit_async_returns_job_url():
    client = TapClient()
    job_url = client.submit_async(
        endpoint=ESO_TAP,
        adql=SHORT_ADQL,
        maxrec=10,
    )
    assert isinstance(job_url, str)
    assert job_url.startswith(ESO_TAP)
    assert "/async" in job_url


@pytest.mark.vcr
def test_load_job_phase_is_valid_uws_phase():
    client = TapClient()
    job_url = client.submit_async(
        endpoint=ESO_TAP,
        adql=SHORT_ADQL,
        maxrec=10,
    )
    job = client.load_job(job_url)
    # Phase right after submit+run() is one of these depending on server scheduling.
    assert job.phase in {
        "PENDING",
        "QUEUED",
        "EXECUTING",
        "COMPLETED",
    }


@pytest.mark.vcr
def test_fetch_completed_result_returns_astropy_table():
    client = TapClient()
    job_url = client.submit_async(
        endpoint=ESO_TAP,
        adql=SHORT_ADQL,
        maxrec=10,
    )
    job = client.load_job(job_url)
    job.wait(phases={"COMPLETED", "ERROR", "ABORTED"}, timeout=60)
    assert job.phase == "COMPLETED"
    table = job.fetch_result().to_table()
    assert "dp_id" in table.colnames
    assert len(table) <= 3


@pytest.mark.vcr
def test_abort_job_then_delete_idempotent():
    client = TapClient()
    job_url = client.submit_async(
        endpoint=ESO_TAP,
        adql=SHORT_ADQL,
        maxrec=10,
    )
    client.abort_job(job_url)  # first call
    client.abort_job(job_url)  # second call must not raise
