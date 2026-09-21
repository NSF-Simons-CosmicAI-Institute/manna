"""run_adql_query mode parameter + auto-promote behavior."""

from types import SimpleNamespace

import pytest
from astropy.table import Table
from fastmcp import Client

from manna.errors import ArchiveError, TimeoutArchiveError
from manna.tools import tap as tap_tools


def _uws_error(message: str):
    """pyvo's real shape for an ERROR job: text at _job.errorsummary.message.content."""
    return SimpleNamespace(errorsummary=SimpleNamespace(message=SimpleNamespace(content=message)))


class _FakeTapClient:
    def __init__(self):
        self.query_table = Table({"ra": [1.0], "dec": [2.0]})
        self.query_raises = None
        self.submit_returns = "https://datalab.noirlab.edu/tap/async/auto-promoted"
        self.submit_calls = 0
        self.load_phases: list[str] = ["EXECUTING"]
        self.load_uws = None

    def query(self, *, endpoint, adql, maxrec):
        if self.query_raises is not None:
            raise self.query_raises
        return self.query_table

    def submit_async(self, *, endpoint, adql, maxrec):
        self.submit_calls += 1
        return self.submit_returns

    def load_job(self, job_url):
        phase = self.load_phases.pop(0) if len(self.load_phases) > 1 else self.load_phases[0]
        return SimpleNamespace(
            phase=phase,
            starttime=None,
            endtime=None,
            _job=self.load_uws if self.load_uws is not None else SimpleNamespace(errorsummary=None),
        )

    def abort_job(self, job_url):
        pass


@pytest.fixture
def fake_tap(monkeypatch):
    client = _FakeTapClient()
    monkeypatch.setattr(tap_tools, "_get_tap", lambda: client)
    return client


@pytest.mark.asyncio
async def test_mode_sync_returns_inline_envelope(mcp_server, fake_tap):
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "run_adql_query",
            {
                "endpoint": "https://datalab.noirlab.edu/tap",
                "adql": "SELECT 1",
                "mode": "sync",
            },
        )
        payload = result.structured_content
        assert "mode" not in payload  # sync envelope is mode-less
        assert payload["row_count"] == 1
        assert payload["rows"] == [[1.0, 2.0]]

    assert fake_tap.submit_calls == 0


@pytest.mark.asyncio
async def test_mode_auto_fast_returns_inline_no_promotion(mcp_server, fake_tap):
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "run_adql_query",
            {
                "endpoint": "https://datalab.noirlab.edu/tap",
                "adql": "SELECT 1",
                "mode": "auto",
            },
        )
        payload = result.structured_content
        assert "mode" not in payload
        assert payload["row_count"] == 1

    assert fake_tap.submit_calls == 0


@pytest.mark.asyncio
async def test_mode_auto_promotes_on_timeout(mcp_server, fake_tap):
    fake_tap.query_raises = TimeoutArchiveError(message="TAP sync request timed out: read timeout")

    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "run_adql_query",
            {
                "endpoint": "https://datalab.noirlab.edu/tap",
                "adql": "SELECT slow_join",
                "mode": "auto",
            },
        )
        payload = result.structured_content
        assert payload["mode"] == "async"
        assert payload["archive"] == "datalab"
        assert payload["phase"] == "EXECUTING"
        assert payload["job_url"].endswith("/async/auto-promoted")

    assert fake_tap.submit_calls == 1


@pytest.mark.asyncio
async def test_mode_auto_does_not_promote_on_syntax_error(mcp_server, fake_tap):
    from manna.errors import DalQueryError

    fake_tap.query_raises = DalQueryError(message="Bad ADQL syntax.")

    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "run_adql_query",
            {
                "endpoint": "https://datalab.noirlab.edu/tap",
                "adql": "SELECT BAD",
                "mode": "auto",
            },
        )
        payload = result.structured_content
        # DalQueryError must propagate unchanged in auto mode — promotion
        # only fires for the timeout failure mode.
        assert payload["error_class"] == "tap_query_error"
        assert fake_tap.submit_calls == 0


@pytest.mark.asyncio
async def test_mode_auto_does_not_promote_on_generic_archive_error(mcp_server, fake_tap):
    # A plain ArchiveError whose message happens to contain "timed out"
    # must NOT promote: the discriminator is the exception TYPE, not the
    # message text. Only TimeoutArchiveError (a real sync timeout) promotes.
    fake_tap.query_raises = ArchiveError(message="upstream 503; service timed out internally")

    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "run_adql_query",
            {
                "endpoint": "https://datalab.noirlab.edu/tap",
                "adql": "SELECT 1",
                "mode": "auto",
            },
        )
        payload = result.structured_content
        assert payload["error_class"] == "archive_error"
        assert "mode" not in payload

    assert fake_tap.submit_calls == 0


@pytest.mark.asyncio
async def test_mode_sync_propagates_timeout_as_archive_error(mcp_server, fake_tap):
    fake_tap.query_raises = ArchiveError(message="TAP sync request timed out.")

    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "run_adql_query",
            {
                "endpoint": "https://datalab.noirlab.edu/tap",
                "adql": "SELECT 1",
                "mode": "sync",
            },
        )
        payload = result.structured_content
        assert payload["error_class"] == "archive_error"
        assert payload["retry_strategy"] == "wait_and_retry"

    assert fake_tap.submit_calls == 0


def _oversize_table() -> Table:
    """A table guaranteed to exceed the inline row cap."""
    from manna.config import get_settings

    n = get_settings().inline_row_limit + 1
    return Table({"ra": list(range(n)), "dec": list(range(n))})


@pytest.mark.asyncio
async def test_mode_sync_oversize_raises_validation_error(mcp_server, fake_tap):
    # A sync result too large to inline does NOT auto-promote — it tells the
    # LLM to re-run with mode='async'. No job is submitted.
    fake_tap.query_table = _oversize_table()

    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "run_adql_query",
            {
                "endpoint": "https://datalab.noirlab.edu/tap",
                "adql": "SELECT * FROM big",
                "mode": "sync",
            },
        )
        payload = result.structured_content
        assert payload["error_class"] == "validation_error"
        assert payload["retry_strategy"] == "fix_and_retry"
        assert "async" in payload["message"]

    assert fake_tap.submit_calls == 0


@pytest.mark.asyncio
async def test_mode_auto_oversize_promotes_to_async(mcp_server, fake_tap):
    # In auto mode, a sync result too large to inline is re-submitted as an
    # async job so the archive holds the bytes and we hand back a job_url.
    fake_tap.query_table = _oversize_table()

    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "run_adql_query",
            {
                "endpoint": "https://datalab.noirlab.edu/tap",
                "adql": "SELECT * FROM big",
                "mode": "auto",
            },
        )
        payload = result.structured_content
        assert payload["mode"] == "async"
        assert payload["job_url"].endswith("/async/auto-promoted")
        assert payload["job_url"] in payload["fetch_recipe"]["code"]

    assert fake_tap.submit_calls == 1


@pytest.mark.asyncio
async def test_mode_async_skips_sync_and_returns_promotion(mcp_server, fake_tap):
    fake_tap.query_raises = RuntimeError("query() must not be called in mode=async")

    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "run_adql_query",
            {
                "endpoint": "https://almascience.nrao.edu/tap",
                "adql": "SELECT TOP 1 * FROM ivoa.obscore",
                "mode": "async",
            },
        )
        payload = result.structured_content
        assert payload["mode"] == "async"
        assert payload["archive"] == "alma"
        assert payload["phase"] == "EXECUTING"

    assert fake_tap.submit_calls == 1


@pytest.mark.asyncio
async def test_mode_async_reports_completed_when_job_finishes_in_window(
    mcp_server, fake_tap, wait_clock
):
    fake_tap.load_phases = ["EXECUTING", "COMPLETED"]

    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "run_adql_query",
            {"endpoint": "https://datalab.noirlab.edu/tap", "adql": "SELECT 1", "mode": "async"},
        )
        payload = result.structured_content

    assert payload["mode"] == "async"
    assert payload["phase"] == "COMPLETED"
    assert payload["next_steps"][0].startswith("The job has already finished")
    assert wait_clock.sleeps == [2.0]


@pytest.mark.asyncio
async def test_mode_async_still_running_after_window_returns_promotion(
    mcp_server, fake_tap, wait_clock
):
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "run_adql_query",
            {"endpoint": "https://datalab.noirlab.edu/tap", "adql": "SELECT 1", "mode": "async"},
        )
        payload = result.structured_content

    assert payload["phase"] == "EXECUTING"
    assert sum(wait_clock.sleeps) == 20.0
    assert "get_async_job_status(job_url)" in payload["next_steps"][0]


@pytest.mark.asyncio
async def test_mode_async_error_in_window_raises_tap_query_error(mcp_server, fake_tap):
    fake_tap.load_phases = ["ERROR"]
    fake_tap.load_uws = _uws_error("Column 'nope' not found")

    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "run_adql_query",
            {"endpoint": "https://datalab.noirlab.edu/tap", "adql": "SELECT nope", "mode": "async"},
        )
        payload = result.structured_content

    assert payload["error_class"] == "tap_query_error"
    assert "nope" in payload["message"]


@pytest.mark.asyncio
async def test_mode_async_aborted_in_window_says_abandon(mcp_server, fake_tap):
    fake_tap.load_phases = ["ABORTED"]

    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "run_adql_query",
            {"endpoint": "https://datalab.noirlab.edu/tap", "adql": "SELECT 1", "mode": "async"},
        )
        payload = result.structured_content

    assert payload["error_class"] == "validation_error"
    assert payload["retry_strategy"] == "abandon"
