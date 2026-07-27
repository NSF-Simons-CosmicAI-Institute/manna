"""Lifecycle tests for vo_tap_status / vo_tap_results / vo_tap_abort
through an in-memory FastMCP client. Backend is faked — no real HTTP."""

from datetime import UTC, datetime

import pytest
from fastmcp import Client

from manna import job_store
from manna.tools import tap as tap_tools


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

    def submit_async(self, *, endpoint, adql, maxrec):
        self.submitted.append((endpoint, adql, maxrec))
        return f"{endpoint}/async/fake-id"

    def load_job(self, job_url):
        return self.job

    def abort_job(self, job_url):
        self.job.delete()

    def query(self, *, endpoint, adql, maxrec):
        raise NotImplementedError("not used in lifecycle tests")


@pytest.fixture(autouse=True)
def _clear_jobs():
    with job_store._LOCK:
        job_store._STORE.clear()
    yield
    with job_store._LOCK:
        job_store._STORE.clear()


@pytest.fixture
def fake_tap(monkeypatch):
    client = _FakeTapClient()
    monkeypatch.setattr(tap_tools, "_get_tap", lambda: client)
    return client


@pytest.mark.asyncio
async def test_status_returns_phase_and_archive(mcp_server, fake_tap):
    job_id, _ = job_store.put(
        job_url="https://datalab.noirlab.edu/tap/async/abc",
        endpoint="https://datalab.noirlab.edu/tap",
        adql="SELECT 1",
    )
    fake_tap.job = _FakeAsyncJob(
        phase="EXECUTING",
        started_at=datetime(2026, 6, 8, 14, 30, tzinfo=UTC),
    )

    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_tap_status", {"job_id": job_id})
        payload = result.structured_content
        assert payload["job_id"] == job_id
        assert payload["phase"] == "EXECUTING"
        assert payload["archive"] == "datalab"
        assert payload["started_at"] == "2026-06-08T14:30:00+00:00"
        assert payload["ended_at"] is None
        assert payload["error_message"] is None


@pytest.mark.asyncio
async def test_status_unknown_job_id_returns_validation_error(mcp_server, fake_tap):
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "vo_tap_status",
            {"job_id": "ffffffffffff"},
        )
        payload = result.structured_content
        assert payload["error_class"] == "validation_error"
        assert payload["retry_strategy"] == "abandon"


@pytest.mark.asyncio
async def test_status_phase_error_surfaces_message(mcp_server, fake_tap):
    job_id, _ = job_store.put(
        job_url="https://example.tap/async/abc",
        endpoint="https://example.tap",
        adql="SELECT bogus",
    )

    class _ErrSummary:
        message = "Syntax error near 'bogus'."

    fake_tap.job = _FakeAsyncJob(phase="ERROR", error_summary=_ErrSummary())

    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_tap_status", {"job_id": job_id})
        payload = result.structured_content
        # status itself never raises on ERROR phase — it reports the phase
        # and the message. results is where ERROR raises.
        assert payload["phase"] == "ERROR"
        assert "Syntax error" in payload["error_message"]


@pytest.mark.asyncio
async def test_results_when_completed_returns_result_url_envelope(mcp_server, fake_tap):
    job_url = "https://datalab.noirlab.edu/tap/async/abc"
    job_id, _ = job_store.put(
        job_url=job_url,
        endpoint="https://datalab.noirlab.edu/tap",
        adql="SELECT TOP 2 ra, dec FROM smash_dr2.object",
    )
    fake_tap.job = _FakeAsyncJob(phase="COMPLETED")

    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_tap_results", {"job_id": job_id})
        payload = result.structured_content
        # No bytes fetched server-side: the client gets URLs + a pyvo recipe.
        assert payload["phase"] == "COMPLETED"
        assert payload["job_url"] == job_url
        assert payload["result_url"].endswith("/results/result")
        assert payload["archive"] == "datalab"
        assert payload["fetch_recipe"]["module"] == "pyvo"
        assert job_url in payload["fetch_recipe"]["code"]
        assert "rows" not in payload


@pytest.mark.asyncio
async def test_results_when_executing_returns_job_not_ready(mcp_server, fake_tap):
    job_id, _ = job_store.put(
        job_url="https://example.tap/async/abc",
        endpoint="https://example.tap",
        adql="SELECT 1",
    )
    fake_tap.job = _FakeAsyncJob(phase="EXECUTING")

    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_tap_results", {"job_id": job_id})
        payload = result.structured_content
        assert payload["error_class"] == "job_not_ready"
        assert payload["retry_strategy"] == "poll"


@pytest.mark.asyncio
async def test_results_when_error_phase_returns_tap_query_error(mcp_server, fake_tap):
    job_id, _ = job_store.put(
        job_url="https://example.tap/async/abc",
        endpoint="https://example.tap",
        adql="SELECT bogus",
    )

    class _ErrSummary:
        message = "Bad syntax."

    fake_tap.job = _FakeAsyncJob(phase="ERROR", error_summary=_ErrSummary())

    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_tap_results", {"job_id": job_id})
        payload = result.structured_content
        assert payload["error_class"] == "tap_query_error"
        assert payload["retry_strategy"] == "fix_and_retry"
        assert "Bad syntax" in payload["message"]


@pytest.mark.asyncio
async def test_results_unknown_job_id_returns_validation_error(mcp_server, fake_tap):
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "vo_tap_results",
            {"job_id": "deadbeef0000"},
        )
        payload = result.structured_content
        assert payload["error_class"] == "validation_error"
        assert payload["retry_strategy"] == "abandon"


@pytest.mark.asyncio
async def test_abort_evicts_job_and_returns_aborted(mcp_server, fake_tap):
    job_id, _ = job_store.put(
        job_url="https://datalab.noirlab.edu/tap/async/abc",
        endpoint="https://datalab.noirlab.edu/tap",
        adql="SELECT 1",
    )

    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_tap_abort", {"job_id": job_id})
        payload = result.structured_content
        assert payload["job_id"] == job_id
        assert payload["phase"] == "ABORTED"
        assert payload["archive"] == "datalab"

    # JobStore entry is gone
    assert job_store.get(job_id) is None
    # Backend abort was called
    assert fake_tap.job.deleted is True


@pytest.mark.asyncio
async def test_abort_is_idempotent_on_unknown_job(mcp_server, fake_tap):
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "vo_tap_abort",
            {"job_id": "feedfacefeed"},
        )
        payload = result.structured_content
        # Spec §2.4: aborting an unknown / already-evicted job returns
        # the canonical aborted payload, not an error.
        assert payload["phase"] == "ABORTED"
        assert payload["job_id"] == "feedfacefeed"
        assert payload["archive"] is None
