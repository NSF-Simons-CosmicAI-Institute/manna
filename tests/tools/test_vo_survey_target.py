import pytest
from astropy.table import Table

import manna.tools._select as sel
import manna.tools.count as count_mod
import manna.tools.survey as survey_mod
from manna.archives._count import ContainsPoint, CountTarget, Q3CRadial
from manna.archives._model import Archive


def _arch(name, wb, mode="sync", geom=None, priority=100):
    return Archive(
        short_name=name,
        display_name=name.upper(),
        host_substrings=(f"{name}.x",),
        tap_url=f"http://{name}/tap",
        waveband=wb,
        priority=priority,
        count_target=CountTarget(
            table=f"{name}.obj", geometry=geom or Q3CRadial("ra", "dec"), mode=mode
        ),
    )


@pytest.fixture
def fleet(monkeypatch):
    archives = (
        _arch("datalab", "optical", priority=1),
        _arch("alma", "millimeter", geom=ContainsPoint("s_ra", "s_dec"), priority=2),
        _arch("nrao", "radio", mode="async", geom=ContainsPoint("s_ra", "s_dec"), priority=3),
    )
    monkeypatch.setattr(sel, "active_archives", lambda: archives)
    monkeypatch.setattr(
        sel, "get_resolver", lambda: type("R", (), {"resolve": lambda s, n: (187.7, 12.4)})()
    )
    return archives


class _FakeTap:
    """A fake TapClient wired under count.py's real _get_tap seam.

    Unlike monkeypatching survey_mod._run_count wholesale, this routes the
    survey through the REAL _run_count / _run_count_async, so the pending-row
    contract (status/count/job_url keys) under test is the actual production
    contract, not a hand-written stand-in that can silently drift from it —
    that drift is exactly what hid a job_id KeyError during a past rebase.
    """

    def __init__(self, *, pending_job_url: str):
        self._pending_job_url = pending_job_url

    def query(self, *, endpoint, adql, maxrec=1):
        n = 842 if "datalab" in endpoint else 37
        return Table({"n": [n]})

    def submit_async(self, *, endpoint, adql, maxrec=1):
        return self._pending_job_url

    def load_job(self, job_url):
        return _FakeStuckJob()


class _FakeStuckJob:
    """An async job that never leaves EXECUTING within the poll budget."""

    phase = "EXECUTING"

    def raise_if_error(self):
        raise AssertionError("should not be called while EXECUTING")

    def fetch_result(self):
        raise AssertionError("should not be called while EXECUTING")


def test_survey_aggregates_all_countable(fleet, monkeypatch):
    from manna.config import get_settings

    # datalab + alma (sync) return counts synchronously through the real
    # _run_count; nrao (async) stays pending once its poll budget is
    # exhausted — shrink the budget so the loop exits fast.
    monkeypatch.setattr(
        count_mod, "_get_tap", lambda: _FakeTap(pending_job_url="http://nrao/job/1")
    )
    monkeypatch.setattr(count_mod, "_sleep", lambda s: None)
    get_settings.cache_clear()
    monkeypatch.setenv("MANNA_COUNT_ASYNC_BUDGET_SECONDS", "1")
    monkeypatch.setenv("MANNA_COUNT_ASYNC_POLL_INTERVAL_SECONDS", "1")
    try:
        out = survey_mod.vo_survey_target(target="M87")
    finally:
        get_settings.cache_clear()

    by = {r["archive"]: r for r in out["archives"]}
    assert by["datalab"]["count"] == 842 and by["datalab"]["status"] == "ok"
    assert by["alma"]["count"] == 37
    assert by["nrao"]["status"] == "pending" and by["nrao"]["job_url"] == "http://nrao/job/1"
    assert "next_steps" in by["nrao"]
    assert out["summary"]["archives_with_data"] == 2
    assert out["summary"]["pending"] == 1
    assert set(out["summary"]["wavebands"]) == {"optical", "millimeter"}


def test_survey_wavebands_filter(fleet, monkeypatch):
    monkeypatch.setattr(
        survey_mod, "_run_count", lambda **k: {"status": "ok", "count": 1, "job_url": None}
    )
    out = survey_mod.vo_survey_target(target="M87", wavebands=["optical"])
    assert [r["archive"] for r in out["archives"]] == ["datalab"]


def test_survey_per_archive_error_isolated(fleet, monkeypatch):
    from manna.errors import ArchiveError

    def flaky(*, endpoint, adql, mode):
        if "alma" in endpoint:
            raise ArchiveError(message="boom")
        return {"status": "ok", "count": 5, "job_url": None}

    monkeypatch.setattr(survey_mod, "_run_count", flaky)

    out = survey_mod.vo_survey_target(target="M87")
    by = {r["archive"]: r for r in out["archives"]}
    assert by["alma"]["status"] == "error"
    assert by["datalab"]["count"] == 5
    assert out["summary"]["errors"] == 1


def test_survey_non_tool_execution_error_isolated(fleet, monkeypatch):
    """A raw (non-ToolExecutionError) blip from one archive's count — e.g. a
    live DALServiceError escaping count.py's async poll loop — must still be
    isolated to that archive's row, not blow up the whole survey as a
    redacted internal_error. Regression for the async-path isolation gap.
    """

    def flaky(*, endpoint, adql, mode):
        if "alma" in endpoint:
            raise RuntimeError("connection reset while polling")
        return {"status": "ok", "count": 5, "job_url": None}

    monkeypatch.setattr(survey_mod, "_run_count", flaky)

    out = survey_mod.vo_survey_target(target="M87")

    # The whole call must still succeed (no top-level error_class) ...
    assert "error_class" not in out
    by = {r["archive"]: r for r in out["archives"]}
    # ... with only the flaky archive's row marked as an error ...
    assert by["alma"]["status"] == "error"
    # ... and every other archive's row unaffected.
    assert by["datalab"]["status"] == "ok" and by["datalab"]["count"] == 5
    assert by["nrao"]["status"] == "ok" and by["nrao"]["count"] == 5
    assert out["summary"]["errors"] == 1


def test_survey_unresolvable_soft_fails(fleet, monkeypatch):
    monkeypatch.setattr(
        sel, "get_resolver", lambda: type("R", (), {"resolve": lambda s, n: None})()
    )
    out = survey_mod.vo_survey_target(target="XYZZY")
    assert out["resolved"] is False


def test_survey_empty_target_validation_error(fleet):
    out = survey_mod.vo_survey_target(target="")
    assert out.get("error_class") == "validation_error"


def test_survey_whitespace_target_validation_error(fleet):
    out = survey_mod.vo_survey_target(target="   ")
    assert out.get("error_class") == "validation_error"
