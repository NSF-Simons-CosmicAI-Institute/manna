"""Real-archive regression guard for the stateless result-URL model.

Unlike test_async_tap_lifecycle.py (fully faked), this exercises the REAL
TapClient backend against recorded HTTP from a live async TAP job. It locks
in the load-bearing assumption of the stateless design: a completed async
job exposes a usable `result_uri`, and vo_tap_results surfaces it as a
`result_url` + pyvo `fetch_recipe` WITHOUT the server fetching any bytes.

GAVO's TAP service is used because its async queue completes effectively
instantly, keeping the cassette small and deterministic. The client-side
fetch round-trip (both recipe paths) was verified live against this service
during development; pyvo owns the fetch itself, so this test guards only the
server contract.

Re-record with:  uv run pytest --record-mode=once -k async_result_url_live
"""

import pytest
from fastmcp import Client

ENDPOINT = "https://dc.g-vo.org/tap"
ADQL = "SELECT TOP 5 table_name FROM tap_schema.tables"


@pytest.mark.vcr
async def test_async_results_return_result_url_and_recipe(mcp_server):
    async with Client(mcp_server) as client:
        # 1) Submit async — promotion carries the real upstream job_url + recipe.
        promotion = await client.call_tool(
            "vo_tap_query",
            {"endpoint": ENDPOINT, "adql": ADQL, "mode": "async"},
        )
        prom = promotion.structured_content
        assert prom["mode"] == "async"
        job_id = prom["job_id"]
        job_url = prom["job_url"]
        assert "/async/" in job_url
        assert job_url in prom["fetch_recipe"]["code"]

        # 2) Poll status — GAVO completes instantly.
        status = await client.call_tool("vo_tap_status", {"job_id": job_id})
        assert status.structured_content["phase"] == "COMPLETED"

        # 3) Results: URL + recipe, no bytes fetched server-side.
        results = await client.call_tool("vo_tap_results", {"job_id": job_id})
        rp = results.structured_content
        assert rp["phase"] == "COMPLETED"
        assert rp["job_url"] == job_url
        assert rp["result_url"].endswith("/results/result")
        assert rp["format"] == "votable"
        assert "rows" not in rp  # server never inlines async results

        recipe = rp["fetch_recipe"]
        assert recipe["module"] == "pyvo"
        assert job_url in recipe["code"]
        # The recipe must be syntactically valid Python the client can run.
        compile(recipe["code"], "<fetch_recipe>", "exec")
