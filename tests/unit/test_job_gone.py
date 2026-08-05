"""A vanished upstream job must tell the LLM to stop, not to keep polling.

Without the JobStore there is no local record saying "this job_id is unknown",
so the only signal that a job is gone is the archive's own 404/410. If that
maps to the default ArchiveError (retry_strategy='wait_and_retry') the model is
told to wait and retry a job that will never come back.
"""

import pytest
import requests
from pyvo.dal.exceptions import DALServiceError

from manna.backends.tap import TapClient
from manna.errors import ArchiveError, JobGoneError

JOB_URL = "https://almascience.eso.org/tap/async/12345"


def _dal_error_with_status(status: int) -> DALServiceError:
    response = requests.Response()
    response.status_code = status
    http_error = requests.exceptions.HTTPError(f"{status}", response=response)
    return DALServiceError.from_except(http_error, url=JOB_URL)


@pytest.fixture
def client():
    return TapClient(sync_timeout_seconds=1.0)


@pytest.mark.parametrize("status", [404, 410])
def test_load_job_maps_gone_status_to_job_gone(monkeypatch, client, status):
    def _raise(*args, **kwargs):
        raise _dal_error_with_status(status)

    monkeypatch.setattr("manna.backends.tap.AsyncTAPJob", _raise)

    with pytest.raises(JobGoneError):
        client.load_job(JOB_URL)


@pytest.mark.parametrize("status", [500, 502, 503])
def test_load_job_keeps_server_errors_retryable(monkeypatch, client, status):
    """A 5xx says the archive is unwell, not that the job is gone."""

    def _raise(*args, **kwargs):
        raise _dal_error_with_status(status)

    monkeypatch.setattr("manna.backends.tap.AsyncTAPJob", _raise)

    with pytest.raises(ArchiveError) as exc:
        client.load_job(JOB_URL)
    assert not isinstance(exc.value, JobGoneError)
    assert exc.value.retry_strategy == "wait_and_retry"


def test_load_job_without_status_stays_archive_error(monkeypatch, client):
    """A transport failure carries no HTTP status; it must remain retryable."""

    def _raise(*args, **kwargs):
        raise DALServiceError(reason="connection reset", url=JOB_URL)

    monkeypatch.setattr("manna.backends.tap.AsyncTAPJob", _raise)

    with pytest.raises(ArchiveError) as exc:
        client.load_job(JOB_URL)
    assert not isinstance(exc.value, JobGoneError)


def test_job_gone_error_tells_the_llm_to_abandon():
    err = JobGoneError(message="gone")
    assert err.error_class == "job_gone"
    assert err.retry_strategy == "abandon"
