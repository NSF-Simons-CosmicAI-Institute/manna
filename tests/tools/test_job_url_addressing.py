"""Async TAP jobs are addressed by their upstream job_url, not a server-side id.

The JobStore used to map an opaque job_id -> job_url. That mapping was the only
cross-request state in the process, and because it carried no notion of caller
identity, any session holding any job_id could read or abort another user's job
in the shared-service deployment.

It also bought nothing: the promotion envelope already handed the LLM the
job_url (and a fetch_recipe built from it), so the id was never concealing the
URL — it was a second, cross-user-reachable path to it.

These tests pin the replacement: the job_url IS the handle.
"""

import importlib

import pytest
from astropy.table import Table
from fastmcp import Client

from manna.tools import tap as tap_tools

ALMA_JOB_URL = "https://almascience.eso.org/tap/async/12345"


class _FakeJob:
    phase = "COMPLETED"
    starttime = None
    endtime = None
    error_summary = None
    result_uri = "https://almascience.eso.org/tap/async/12345/results/result"


class _FakeTapClient:
    def __init__(self):
        self.submit_returns = ALMA_JOB_URL
        self.aborted = []
        self.loaded = []

    def query(self, *, endpoint, adql, maxrec):
        return Table({"ra": [1.0], "dec": [2.0]})

    def submit_async(self, *, endpoint, adql, maxrec):
        return self.submit_returns

    def load_job(self, job_url):
        self.loaded.append(job_url)
        return _FakeJob()

    def abort_job(self, job_url):
        self.aborted.append(job_url)


@pytest.fixture
def fake_tap(monkeypatch):
    client = _FakeTapClient()
    monkeypatch.setattr(tap_tools, "_get_tap", lambda: client)
    return client


def test_job_store_module_is_gone():
    """The store is deleted outright, not merely unused."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("manna.job_store")


@pytest.mark.asyncio
async def test_promotion_envelope_carries_job_url_and_no_job_id(mcp_server, fake_tap):
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "vo_tap_query",
            {
                "endpoint": "https://almascience.eso.org/tap",
                "adql": "SELECT 1",
                "mode": "async",
            },
        )
        payload = result.structured_content

    assert payload["mode"] == "async"
    assert payload["job_url"] == ALMA_JOB_URL
    assert "job_id" not in payload
    assert payload["archive"] == "alma"


@pytest.mark.asyncio
async def test_next_steps_reference_job_url(mcp_server, fake_tap):
    """The handoff instructions must name the parameter the tools now take.

    Small local models follow these literally; leaving 'job_id' in the prose
    would send them looking for a field that no longer exists.
    """
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "vo_tap_query",
            {
                "endpoint": "https://almascience.eso.org/tap",
                "adql": "SELECT 1",
                "mode": "async",
            },
        )
        steps = " ".join(result.structured_content["next_steps"])

    assert "job_url" in steps
    assert "job_id" not in steps


@pytest.mark.asyncio
async def test_status_takes_a_job_url(mcp_server, fake_tap):
    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_tap_status", {"job_url": ALMA_JOB_URL})
        payload = result.structured_content

    assert payload["phase"] == "COMPLETED"
    assert payload["job_url"] == ALMA_JOB_URL
    assert payload["archive"] == "alma"
    assert fake_tap.loaded == [ALMA_JOB_URL]


@pytest.mark.asyncio
async def test_results_takes_a_job_url(mcp_server, fake_tap):
    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_tap_results", {"job_url": ALMA_JOB_URL})
        payload = result.structured_content

    assert payload["job_url"] == ALMA_JOB_URL
    assert payload["archive"] == "alma"
    assert ALMA_JOB_URL in payload["fetch_recipe"]["code"]


@pytest.mark.asyncio
async def test_abort_takes_a_job_url(mcp_server, fake_tap):
    async with Client(mcp_server) as client:
        result = await client.call_tool("vo_tap_abort", {"job_url": ALMA_JOB_URL})
        payload = result.structured_content

    assert payload["phase"] == "ABORTED"
    assert payload["archive"] == "alma"
    assert fake_tap.aborted == [ALMA_JOB_URL]


@pytest.mark.parametrize("tool", ["vo_tap_status", "vo_tap_results", "vo_tap_abort"])
@pytest.mark.asyncio
async def test_job_url_is_ssrf_guarded(mcp_server, fake_tap, tool):
    """job_url is user-supplied and gets fetched — and abort sends DELETE.

    An arbitrary-target DELETE is the sharpest edge introduced by dropping the
    store, so the guard must cover these three the same as `endpoint`.
    """
    async with Client(mcp_server) as client:
        result = await client.call_tool(tool, {"job_url": "http://169.254.169.254/async/1"})
        payload = result.structured_content

    assert payload["error_class"] == "validation_error"
    assert payload["retry_strategy"] == "abandon"
    assert fake_tap.aborted == []
    assert fake_tap.loaded == []


@pytest.mark.asyncio
async def test_health_no_longer_reports_a_job_store(mcp_server):
    from httpx import ASGITransport, AsyncClient

    from manna.app import build_app

    app = build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/health")).json()

    assert body["status"] == "ok"
    assert "job_store" not in body
