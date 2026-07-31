"""Lifecycle tests for vo_tap_status / vo_tap_results / vo_tap_abort
through an in-memory FastMCP client. Backend is faked — no real HTTP.

Jobs are addressed by their upstream job_url; there is no server-side job
registry to seed, so each test simply passes the URL it cares about.
"""

from datetime import UTC, datetime

import pytest
from fastmcp import Client

from manna.errors import JobGoneError
from manna.tools import tap as tap_tools

DATALAB_JOB = "https://datalab.noirlab.edu/tap/async/abc"
ALMA_JOB = "https://almascience.eso.org/tap/async/xyz"


class _FakeAsyncJob:
    """Minimal AsyncTAPJob stand-in for test purposes."""

    def __init__(
        self,
        phase="EXECUTING",
        started_at=None,
        ended_at=None,
        error_summary=None,
        result_uri="https://datalab.noirlab.edu/tap/async/abc/results/result",
    ):
        self.phase = phase
        self.starttime = started_at
        self.endtime = ended_at
        self._error_summary = error_summary
        self.result_uri = result_uri
        self.deleted = False

    @property
    def error_summary(self):
        return self._error_summary

    def delete(self):
        self.deleted = True


class _FakeTapClient:
    """Holds a single fake job; load_job returns it regardless of URL."""

    def __init__(self, job=None):
        self.job = job or _FakeAsyncJob()
        self.submitted = []
        self.load_raises = None

    def submit_async(self, *, endpoint, adql, maxrec):
        self.submitted.append((endpoint, adql, maxrec))
        return f"{endpoint}/async/fake-id"

    def load_job(self, job_url):
        if self.load_raises is not None:
            raise self.load_raises
        return self.job

    def abort_job(self, job_url):
        self.job.delete()

    def query(self, *, endpoint, adql, maxrec):
        raise NotImplementedError("not used in lifecycle tests")


@pytest.fixture
def fake_tap(monkeypatch):
    client = _FakeTapClient()
    monkeypatch.setattr(tap_tools, "_get_tap", lambda: client)
    return client


@pytest.mark.asyncio
async def test_status_returns_phase_and_archive(mcp_server, fake_tap):
    fake_tap.job = _FakeAsyncJob(
        phase="EXECUTING",
        started_at=datetime(2026, 6, 8, 14, 30, tzinfo=UTC),
    )

    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_tap_status", {"job_url": DATALAB_JOB})
        payload = result.structured_content
        assert payload["job_url"] == DATALAB_JOB
        assert payload["phase"] == "EXECUTING"
        assert payload["archive"] == "datalab"
        assert payload["started_at"] == "2026-06-08T14:30:00+00:00"
        assert payload["ended_at"] is None
        assert payload["error_message"] is None


@pytest.mark.asyncio
async def test_status_on_vanished_job_says_abandon(mcp_server, fake_tap):
    """Replaces the old unknown-job_id test.

    A job the archive has dropped is now discovered upstream (404/410) rather
    than by a miss in a local registry — but the advice must still be 'stop',
    never 'wait and retry'.
    """
    fake_tap.load_raises = JobGoneError(message="gone")

    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_tap_status", {"job_url": DATALAB_JOB})
        payload = result.structured_content
        assert payload["error_class"] == "job_gone"
        assert payload["retry_strategy"] == "abandon"


@pytest.mark.asyncio
async def test_status_phase_error_surfaces_message(mcp_server, fake_tap):
    class _ErrSummary:
        message = "Syntax error near 'bogus'."

    fake_tap.job = _FakeAsyncJob(phase="ERROR", error_summary=_ErrSummary())

    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_tap_status", {"job_url": ALMA_JOB})
        payload = result.structured_content
        # status itself never raises on ERROR phase — it reports the phase
        # and the message. results is where ERROR raises.
        assert payload["phase"] == "ERROR"
        assert "Syntax error" in payload["error_message"]


@pytest.mark.asyncio
async def test_results_when_completed_returns_result_url_envelope(mcp_server, fake_tap):
    fake_tap.job = _FakeAsyncJob(phase="COMPLETED")

    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_tap_results", {"job_url": DATALAB_JOB})
        payload = result.structured_content
        # No bytes fetched server-side: the client gets URLs + a pyvo recipe.
        assert payload["phase"] == "COMPLETED"
        assert payload["job_url"] == DATALAB_JOB
        assert payload["result_url"].endswith("/results/result")
        assert payload["archive"] == "datalab"
        assert payload["fetch_recipe"]["module"] == "pyvo"
        assert DATALAB_JOB in payload["fetch_recipe"]["code"]
        assert "rows" not in payload


@pytest.mark.asyncio
async def test_results_when_executing_returns_job_not_ready(mcp_server, fake_tap):
    fake_tap.job = _FakeAsyncJob(phase="EXECUTING")

    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_tap_results", {"job_url": ALMA_JOB})
        payload = result.structured_content
        assert payload["error_class"] == "job_not_ready"
        assert payload["retry_strategy"] == "poll"


@pytest.mark.asyncio
async def test_results_when_error_phase_returns_tap_query_error(mcp_server, fake_tap):
    class _ErrSummary:
        message = "Bad syntax."

    fake_tap.job = _FakeAsyncJob(phase="ERROR", error_summary=_ErrSummary())

    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_tap_results", {"job_url": ALMA_JOB})
        payload = result.structured_content
        assert payload["error_class"] == "tap_query_error"
        assert payload["retry_strategy"] == "fix_and_retry"
        assert "Bad syntax" in payload["message"]


@pytest.mark.asyncio
async def test_results_on_vanished_job_says_abandon(mcp_server, fake_tap):
    fake_tap.load_raises = JobGoneError(message="gone")

    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_tap_results", {"job_url": ALMA_JOB})
        payload = result.structured_content
        assert payload["error_class"] == "job_gone"
        assert payload["retry_strategy"] == "abandon"


@pytest.mark.asyncio
async def test_abort_deletes_upstream_and_returns_aborted(mcp_server, fake_tap):
    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_tap_abort", {"job_url": DATALAB_JOB})
        payload = result.structured_content
        assert payload["job_url"] == DATALAB_JOB
        assert payload["phase"] == "ABORTED"
        assert payload["archive"] == "datalab"

    assert fake_tap.job.deleted is True


@pytest.mark.asyncio
async def test_abort_is_idempotent_on_already_deleted_job(mcp_server, fake_tap):
    """Spec §2.4: aborting a job that is already gone returns the canonical
    aborted payload, not an error.

    The idempotency now lives in the backend — abort_job swallows the upstream
    4xx — rather than in a local-registry miss.
    """

    def _already_gone(job_url):
        pass

    fake_tap.abort_job = _already_gone

    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_tap_abort", {"job_url": DATALAB_JOB})
        payload = result.structured_content
        assert payload["phase"] == "ABORTED"
        assert payload["job_url"] == DATALAB_JOB
        assert payload["archive"] == "datalab"
