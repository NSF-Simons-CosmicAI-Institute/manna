"""Contract: success envelopes from the primitive query tools carry
query_fingerprint + save_recipe; error payloads never do; the recipe text
keeps its load-bearing phrases (QUOTE_ALL quoting, catalog path, the
do-not-re-run imperative — the PR-#64 lesson: weakest-reader phrasing)."""

from astropy.table import Table

from manna.errors import DalQueryError
from manna.shaper import build_save_recipe
from manna.tools import cone as cone_tools
from manna.tools import sia as sia_tools
from manna.tools import tap as tap_tools

_EP = "https://example.org/tap"


class _FakeOk:
    def query(self, **_):
        return Table({"ra": [1.0]})

    def search(self, **_):
        return Table({"ra": [1.0]})


class _FakeErr:
    def query(self, **_):
        raise DalQueryError(message="rejected")

    def search(self, **_):
        raise DalQueryError(message="rejected")


def test_success_envelopes_carry_cache_fields(monkeypatch):
    monkeypatch.setattr(tap_tools, "_get_tap", lambda: _FakeOk())
    monkeypatch.setattr(cone_tools, "_get_cone", lambda: _FakeOk())
    monkeypatch.setattr(sia_tools, "_get_sia", lambda: _FakeOk())
    envelopes = [
        tap_tools.vo_tap_query(endpoint=_EP, adql="SELECT 1", mode="sync"),
        cone_tools.vo_cone_search(endpoint=_EP, ra=1.0, dec=2.0, radius_deg=0.1),
        sia_tools.vo_sia_search(endpoint=_EP, ra=1.0, dec=2.0, size_deg=0.1),
    ]
    for env in envelopes:
        assert isinstance(env["query_fingerprint"], str)
        recipe = env["save_recipe"]
        assert set(recipe) == {"path", "instructions", "code"}
        assert recipe["path"] == f"manna_cache/{env['query_fingerprint']}.csv"
        assert isinstance(env["next_steps"], list)
        assert any("save_recipe.code" in step for step in env["next_steps"])


def test_error_payloads_never_carry_cache_fields(monkeypatch):
    monkeypatch.setattr(tap_tools, "_get_tap", lambda: _FakeErr())
    monkeypatch.setattr(cone_tools, "_get_cone", lambda: _FakeErr())
    monkeypatch.setattr(sia_tools, "_get_sia", lambda: _FakeErr())
    payloads = [
        tap_tools.vo_tap_query(endpoint=_EP, adql="SELECT 1", mode="sync"),
        cone_tools.vo_cone_search(endpoint=_EP, ra=1.0, dec=2.0, radius_deg=0.1),
        sia_tools.vo_sia_search(endpoint=_EP, ra=1.0, dec=2.0, size_deg=0.1),
    ]
    for p in payloads:
        assert "error_class" in p
        assert "query_fingerprint" not in p
        assert "save_recipe" not in p


class _FakeErrorJob:
    phase = "ERROR"

    class error_summary:  # noqa: N801 — mirrors pyvo's attribute-object shape
        message = "upstream query failed"


class _FakeTapWithErrorJob:
    def load_job(self, job_url):
        return _FakeErrorJob()


def test_async_results_error_payload_never_carries_cache_fields(monkeypatch):
    """vo_tap_results on a job that ended in ERROR must surface the standard
    error envelope (error_class + retry_strategy) and must NOT carry
    query_fingerprint/save_recipe — those are attached only on the success
    path, after shape_result_url, which this path never reaches."""
    monkeypatch.setattr(tap_tools, "_get_tap", lambda: _FakeTapWithErrorJob())
    payload = tap_tools.vo_tap_results(job_url="https://example.org/tap/async/99")
    assert "error_class" in payload
    assert "retry_strategy" in payload
    assert "query_fingerprint" not in payload
    assert "save_recipe" not in payload


def test_recipe_text_keeps_load_bearing_phrases():
    r = build_save_recipe(
        fingerprint="abc123def456",
        tool="tap",
        endpoint=_EP,
        archive="alma",
        query="SELECT 1",
        truncated=False,
    )
    assert "csv.QUOTE_ALL" in r["code"]
    assert "manna_cache/catalog.csv" in r["code"]
    assert "makedirs" in r["code"]
    assert "re-run" in r["instructions"].lower()
