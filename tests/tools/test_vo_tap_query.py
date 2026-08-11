"""End-to-end integration test for vo_tap_query through an in-memory MCP client.

The test mounts the real FastMCP server (via the ``mcp_server`` fixture) and
talks to it with ``fastmcp.Client``. Network traffic is recorded with vcrpy.
"""

import pytest
from astropy.table import Table as _Table
from fastmcp import Client

from manna._fingerprint import query_fingerprint as _qfp
from manna.errors import DalQueryError, ValidationError
from manna.tools import tap as ivoa_tools


@pytest.mark.vcr
async def test_vo_tap_query_via_in_memory_client(mcp_server):
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "vo_tap_query",
            {
                "endpoint": "https://datalab.noirlab.edu/tap",
                "adql": (
                    "SELECT TOP 3 ra, dec FROM smash_dr2.object "
                    "WHERE ra BETWEEN 185 AND 185.01 ORDER BY ra"
                ),
                "maxrec": 10,
            },
        )
        payload = result.structured_content
        assert payload["row_count"] <= 3
        assert payload["truncated"] is False
        assert payload["archive"] == "datalab"
        names = {c["name"] for c in payload["columns"]}
        assert {"ra", "dec"}.issubset(names)


async def test_vo_tap_query_validation_error_surface(mcp_server):
    async with Client(mcp_server) as client:
        # raise_on_error=False so we can inspect the surfaced error shape
        # rather than catching the framework-level ToolError exception.
        result = await client.call_tool(
            "vo_tap_query",
            {
                "endpoint": "https://datalab.noirlab.edu/tap",
                "adql": "SELECT TOP 3 ra FROM x",
                "maxrec": -1,  # violates Field(ge=1)
            },
            raise_on_error=False,
        )
        # FastMCP 3.3.1 surfaces Pydantic validation as a framework-level tool
        # error: is_error=True with the message in result.content (TextContent).
        # If a future version starts shipping our error payload through
        # structured_content instead, the discriminator is `error_class`.
        if result.is_error:
            content_text = "".join(getattr(c, "text", "") for c in result.content)
            assert "maxrec" in content_text
        else:
            payload = result.structured_content
            assert payload.get("error_class") is not None


class _FakeTap:
    def __init__(self, exc):
        self._exc = exc

    def query(self, **_kw):
        raise self._exc


@pytest.mark.parametrize(
    ("exc", "expected_error_class"),
    [
        (DalQueryError(message="column not found"), "tap_query_error"),
        (ValidationError(message="bad endpoint", hint="see docs"), "validation_error"),
        (RuntimeError("upstream blew up"), "internal_error"),
    ],
)
def test_vo_tap_query_error_path_returns_structured_payload(exc, expected_error_class, monkeypatch):
    """When the backend raises, vo_tap_query returns a structured payload
    keyed on ``error_class`` (NOT ``isError``). The protocol-level
    ``is_error`` flag is FastMCP's separate concern.
    """
    monkeypatch.setattr(ivoa_tools, "_get_tap", lambda: _FakeTap(exc))
    payload = ivoa_tools.vo_tap_query(
        endpoint="https://datalab.noirlab.edu/tap",
        adql="SELECT 1",
        maxrec=10,
    )
    assert "isError" not in payload, (
        "isError key should not be in the payload (see ivoa.py docstring)"
    )
    assert payload["error_class"] == expected_error_class
    assert "retry_strategy" in payload


# --------------------------------------------------------------------------- #
# the shipped few-shot example must not teach a trap
#
# The old example ran CONTAINS(POINT(...)) against smash_dr2.object, a Data Lab
# table. Verified live 2026-07-15: it fails with
#   "function point(unknown, double precision, double precision) does not exist"
# — the exact construct datalab.py's geometry-contains-untranslated note
# documents as broken and tasks.yaml's t3-datalab-geometry docks models for
# emitting. The Field description is re-sent to the model on EVERY turn, so we
# taught the trap continuously and then penalized the model for copying us.
# --------------------------------------------------------------------------- #
def _adql_field_examples() -> list[str]:
    """The `examples` the model actually sees on vo_tap_query's adql parameter."""
    import inspect

    from manna.tools.tap import vo_tap_query

    param = inspect.signature(vo_tap_query).parameters["adql"]
    field = param.annotation.__metadata__[0]
    return list(field.examples or [])


def _datalab_examples() -> list[str]:
    return [e for e in _adql_field_examples() if "smash_dr2" in e or "nsc_dr2" in e]


def test_datalab_example_does_not_teach_the_geometry_trap():
    examples = _datalab_examples()
    assert examples, "expected at least one Data Lab example"
    for example in examples:
        assert "CONTAINS(" not in example.upper()
        assert "POINT(" not in example.upper()


def test_datalab_example_uses_the_verified_q3c_form():
    assert any("q3c_radial_query" in e and "= 't'" in e for e in _datalab_examples()), (
        "Data Lab cones need q3c_radial_query(...) = 't' — the = 't' literal is required"
    )


def test_an_example_still_shows_standard_geometry_for_obscore():
    """CONTAINS genuinely works on obscore services — don't overcorrect into
    teaching that ADQL geometry is universally broken."""
    obscore = [e for e in _adql_field_examples() if "obscore" in e.lower()]
    assert obscore, "expected an obscore example"
    assert any("CONTAINS(" in e.upper() for e in obscore)


# --------------------------------------------------------------------------- #
# cache envelope fields (query_fingerprint + save_recipe)
# --------------------------------------------------------------------------- #

_EP = "https://example.org/tap"


class _FakeTapInline:
    def query(self, **_):
        return _Table({"ra": [1.0, 2.0], "dec": [3.0, 4.0]})


def test_inline_envelope_carries_cache_fields(monkeypatch):
    from manna.tools import tap as tap_tools

    monkeypatch.setattr(tap_tools, "_get_tap", lambda: _FakeTapInline())
    out = tap_tools.vo_tap_query(endpoint=_EP, adql="SELECT ra, dec FROM t", mode="sync")
    assert out["query_fingerprint"] == _qfp("tap", _EP, "SELECT ra, dec FROM t")
    assert out["save_recipe"]["path"] == f"manna_cache/{out['query_fingerprint']}.csv"
    assert "catalog.csv" in out["save_recipe"]["code"]
    assert "SELECT ra, dec FROM t" in out["load_recipe"]["code"]
    assert "run_sync" in out["load_recipe"]["code"]


def test_auto_mode_fast_path_also_carries_cache_fields(monkeypatch):
    """mode='auto' has its own inline return distinct from mode='sync' — a
    literal-string edit that only matches one of the two returns (they sit
    at different indentation levels) would wire one and silently miss the
    other. Regression guard for exactly that."""
    from manna.tools import tap as tap_tools

    monkeypatch.setattr(tap_tools, "_get_tap", lambda: _FakeTapInline())
    out = tap_tools.vo_tap_query(endpoint=_EP, adql="SELECT ra, dec FROM t", mode="auto")
    assert out["query_fingerprint"] == _qfp("tap", _EP, "SELECT ra, dec FROM t")
    assert "save_recipe" in out
    assert "SELECT ra, dec FROM t" in out["load_recipe"]["code"]


def test_endpoint_from_job_url_standard_uws_layout():
    from manna.tools.tap import _endpoint_from_job_url

    assert (
        _endpoint_from_job_url("https://example.org/tap/async/1234567") == "https://example.org/tap"
    )


def test_endpoint_from_job_url_without_async_segment_returns_unchanged():
    from manna.tools.tap import _endpoint_from_job_url

    job_url = "https://example.org/tap/weird-nonstandard-path"
    assert _endpoint_from_job_url(job_url) == job_url


class _FakeCompletedJob:
    phase = "COMPLETED"
    query = "SELECT ra FROM big_table"
    result_uri = "https://example.org/tap/async/42/results/result"


class _FakeTapWithJob:
    def load_job(self, job_url):
        return _FakeCompletedJob()


def test_tap_results_fingerprints_job_adql(monkeypatch):
    from manna.tools import tap as tap_tools

    monkeypatch.setattr(tap_tools, "_get_tap", lambda: _FakeTapWithJob())
    out = tap_tools.vo_tap_results(job_url="https://example.org/tap/async/42")
    # Same fingerprint the original vo_tap_query would have produced: the
    # endpoint is recovered from the job_url, the ADQL from the job itself.
    assert out["query_fingerprint"] == _qfp("tap", _EP, "SELECT ra FROM big_table")
    assert "save_recipe" in out


def test_tap_results_envelope_does_not_carry_load_recipe(monkeypatch):
    """fetch_recipe already covers loading async results client-side, so
    vo_tap_results must not attach a load_recipe."""
    from manna.tools import tap as tap_tools

    monkeypatch.setattr(tap_tools, "_get_tap", lambda: _FakeTapWithJob())
    out = tap_tools.vo_tap_results(job_url="https://example.org/tap/async/42")
    assert "load_recipe" not in out


class _FakeCompletedJobNoQuery:
    phase = "COMPLETED"
    result_uri = None


class _FakeTapWithBareJob:
    def load_job(self, job_url):
        return _FakeCompletedJobNoQuery()


def test_tap_results_falls_back_to_job_url_identity(monkeypatch):
    from manna.tools import tap as tap_tools

    monkeypatch.setattr(tap_tools, "_get_tap", lambda: _FakeTapWithBareJob())
    job_url = "https://example.org/tap/async/43"
    out = tap_tools.vo_tap_results(job_url=job_url)
    assert out["query_fingerprint"] == _qfp("tap", _EP, job_url)
