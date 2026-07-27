"""End-to-end workflow: async TAP lifecycle as the LLM would experience it.

Steps the LLM takes when a sync query times out (or it picks mode='async'
explicitly):

    1. vo_tap_query(mode='async')      → promotion envelope with job_id + job_url
    2. vo_tap_status(job_id)           → phase
    3. (poll until COMPLETED)
    4. vo_tap_results(job_id)          → result_url + pyvo fetch_recipe

Per-tool tests already cover each step in isolation. This file verifies
the *chain* — specifically that the job_id round-trips correctly and the
final envelope hands the client an upstream URL + fetch recipe (the
server never fetches the result bytes itself).

The TapClient backend is faked so this stays hermetic + fast.
"""

import pytest
from fastmcp import Client

from manna import job_store
from manna.tools import tap as tap_tools


class _FakeAsyncJob:
    """Minimal AsyncTAPJob stand-in. Stateful: mutable phase + result."""

    def __init__(self):
        self.phase = "EXECUTING"
        self.starttime = None
        self.endtime = None
        self._error_summary = None
        self.result_uri = "https://archive.example/tap/async/test-job-id/results/result"

    @property
    def error_summary(self):
        return self._error_summary

    def delete(self):
        pass


class _FakeTapClient:
    def __init__(self):
        self.job = _FakeAsyncJob()
        self.submit_calls: list[tuple] = []

    def submit_async(self, *, endpoint, adql, maxrec):
        self.submit_calls.append((endpoint, adql, maxrec))
        return f"{endpoint}/async/test-job-id"

    def load_job(self, job_url):
        return self.job

    def abort_job(self, job_url):
        self.job.delete()

    def query(self, *, endpoint, adql, maxrec):
        raise NotImplementedError("workflow tests use async only")


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
async def test_full_lifecycle_promotion_status_results(mcp_server, fake_tap):
    """The headline chain. Verify the same job_id flows from promotion
    through status (mid-flight) to results (after completion), and the
    final envelope hands the client the upstream job_url + result_url +
    a pyvo fetch_recipe (no bytes fetched server-side)."""
    async with Client(mcp_server) as client:
        # Step 1: explicit async kick-off
        promotion = await client.call_tool(
            "vo_tap_query",
            {
                "endpoint": "https://data-query.nrao.edu/tap",
                "adql": "SELECT TOP 5 obs_publisher_did FROM tap_schema.obscore",
                "mode": "async",
            },
        )
        prom_payload = promotion.structured_content
        assert prom_payload["mode"] == "async"
        assert prom_payload["phase"] == "EXECUTING"
        job_id = prom_payload["job_id"]
        assert len(job_id) == 12
        # The promotion already carries the real upstream job URL + recipe.
        job_url = prom_payload["job_url"]
        assert job_url.endswith("/async/test-job-id")
        assert job_url in prom_payload["fetch_recipe"]["code"]

        # Step 2: check status — still mid-flight
        status = await client.call_tool("vo_tap_status", {"job_id": job_id})
        assert status.structured_content["phase"] == "EXECUTING"
        assert status.structured_content["job_id"] == job_id

        # Step 3: try to fetch results — should get job_not_ready
        early = await client.call_tool("vo_tap_results", {"job_id": job_id})
        assert early.structured_content["error_class"] == "job_not_ready"
        assert early.structured_content["retry_strategy"] == "poll"

        # Step 4: backend completes the job
        fake_tap.job.phase = "COMPLETED"

        # Step 5: status reports COMPLETED
        status = await client.call_tool("vo_tap_status", {"job_id": job_id})
        assert status.structured_content["phase"] == "COMPLETED"

        # Step 6: results return a result-URL envelope + fetch recipe
        results = await client.call_tool("vo_tap_results", {"job_id": job_id})
        rp = results.structured_content
        assert rp["phase"] == "COMPLETED"
        assert rp["job_url"] == job_url
        assert rp["result_url"].endswith("/results/result")
        assert rp["fetch_recipe"]["module"] == "pyvo"
        assert job_url in rp["fetch_recipe"]["code"]
        # The server must NOT inline result rows anymore.
        assert "rows" not in rp


@pytest.mark.asyncio
async def test_chain_abort_invalidates_subsequent_status(mcp_server, fake_tap):
    """User aborts mid-flight; status/results on the same job_id must
    surface as validation_error (the JobStore entry is evicted)."""
    async with Client(mcp_server) as client:
        promotion = await client.call_tool(
            "vo_tap_query",
            {
                "endpoint": "https://almascience.nrao.edu/tap",
                "adql": "SELECT 1",
                "mode": "async",
            },
        )
        job_id = promotion.structured_content["job_id"]

        # Abort
        abort = await client.call_tool("vo_tap_abort", {"job_id": job_id})
        assert abort.structured_content["phase"] == "ABORTED"

        # Subsequent status: unknown job_id
        status = await client.call_tool("vo_tap_status", {"job_id": job_id})
        assert status.structured_content["error_class"] == "validation_error"
        assert status.structured_content["retry_strategy"] == "abandon"


@pytest.mark.asyncio
async def test_chain_handles_phase_error_with_message(mcp_server, fake_tap):
    """Bad ADQL: phase=ERROR → vo_tap_results raises tap_query_error
    with the upstream message (when available)."""
    async with Client(mcp_server) as client:
        promotion = await client.call_tool(
            "vo_tap_query",
            {
                "endpoint": "https://data-query.nrao.edu/tap",
                "adql": "SELECT BAD",
                "mode": "async",
            },
        )
        job_id = promotion.structured_content["job_id"]

        # Upstream completes with ERROR + message
        class _ErrSummary:
            message = "Syntax error: unexpected token BAD"

        fake_tap.job.phase = "ERROR"
        fake_tap.job._error_summary = _ErrSummary()

        results = await client.call_tool("vo_tap_results", {"job_id": job_id})
        rp = results.structured_content
        assert rp["error_class"] == "tap_query_error"
        assert rp["retry_strategy"] == "fix_and_retry"
        assert "Syntax error" in rp["message"]


@pytest.mark.asyncio
async def test_chain_handles_phase_error_with_empty_message(mcp_server, fake_tap):
    """NRAO regression: when the upstream sends phase=ERROR with no
    error_summary (N-06 finding), the chain must still produce a
    structured payload — not crash."""
    async with Client(mcp_server) as client:
        promotion = await client.call_tool(
            "vo_tap_query",
            {
                "endpoint": "https://data-query.nrao.edu/tap",
                "adql": "SELECT LOWER(instrument_name) FROM tap_schema.obscore",
                "mode": "async",
            },
        )
        job_id = promotion.structured_content["job_id"]

        fake_tap.job.phase = "ERROR"
        fake_tap.job._error_summary = None  # the NRAO regression case

        results = await client.call_tool("vo_tap_results", {"job_id": job_id})
        rp = results.structured_content
        assert rp["error_class"] == "tap_query_error"
        # Message must be SOMETHING actionable, even if upstream gave nothing
        assert rp["message"]
        assert "ERROR" in rp["message"]
