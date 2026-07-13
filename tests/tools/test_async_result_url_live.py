"""Real-archive regression guard for the stateless result-URL model.

Unlike test_async_tap_lifecycle.py (fully faked), this exercises the REAL
TapClient backend against recorded HTTP from a live async TAP job. It locks
in the load-bearing assumption of the stateless design: a completed async
job exposes a usable `result_uri`, and vo_tap_results surfaces it as a
`result_url` + pyvo `fetch_recipe` WITHOUT the server fetching any bytes.

GAVO and ALMA are used because their async queues complete effectively
instantly, keeping the cassettes small and deterministic. They also
deliberately exercise two DIFFERENT `result_uri` schemes — GAVO returns the
standard UWS `.../results/result`, while ALMA returns a custom
`.../tap/files/result_<id>.xml`. This guards the design choice to READ
`job.result_uri` (resolved by pyvo from the job's UWS XML) rather than
CONSTRUCT `{job_url}/results/result`, which would be wrong for ALMA.

The client-side fetch round-trip (both recipe paths) was verified live
against GAVO, ALMA, and NOIRLab Data Lab during development; pyvo owns the
fetch itself, so this test guards only the server contract.

Re-record with:  uv run pytest --record-mode=once -k async_result_url_live
"""

import pytest
from fastmcp import Client

CASES = {
    "gavo": ("https://dc.g-vo.org/tap", "SELECT TOP 5 table_name FROM tap_schema.tables"),
    "alma": (
        "https://almascience.nrao.edu/tap",
        "SELECT TOP 5 target_name, s_ra, s_dec FROM ivoa.obscore",
    ),
}


@pytest.mark.vcr
@pytest.mark.parametrize("case", list(CASES), ids=list(CASES))
async def test_async_results_return_result_url_and_recipe(mcp_server, case):
    endpoint, adql = CASES[case]
    async with Client(mcp_server) as client:
        # 1) Submit async — promotion carries the real upstream job_url + recipe.
        promotion = await client.call_tool(
            "vo_tap_query",
            {"endpoint": endpoint, "adql": adql, "mode": "async"},
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
        assert rp["format"] == "votable"
        assert "rows" not in rp  # server never inlines async results

        # result_url is read from the job's UWS XML, NOT constructed — its
        # scheme is archive-specific (GAVO: .../results/result;
        # ALMA: .../tap/files/result_<id>.xml). Assert only that it is a
        # real, non-empty URL and that the recipe's astropy alternative uses it.
        result_url = rp["result_url"]
        assert result_url and result_url.startswith("http")

        recipe = rp["fetch_recipe"]
        assert recipe["module"] == "pyvo"
        assert job_url in recipe["code"]
        assert result_url in recipe["alternative"]
        # The recipe must be syntactically valid Python the client can run.
        compile(recipe["code"], "<fetch_recipe>", "exec")
