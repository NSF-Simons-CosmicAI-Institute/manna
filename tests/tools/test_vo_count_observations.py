import pytest
from astropy.table import Table

import manna.tools._select as sel
import manna.tools.count as count_mod
from manna.archives._count import ContainsPoint, CountTarget, Q3CRadial
from manna.archives._model import Archive


def _archive(name, *, waveband, mode="sync", geom=None, tap="http://x/tap", priority=100):
    return Archive(
        short_name=name,
        display_name=name.upper(),
        host_substrings=(f"{name}.x",),
        tap_url=tap,
        waveband=waveband,
        priority=priority,
        count_target=CountTarget(
            table=f"{name}.obj", geometry=geom or Q3CRadial("ra", "dec"), mode=mode
        ),
    )


class _FakeTap:
    def __init__(self, *, sync_table=None, sync_exc=None):
        self._sync_table = sync_table
        self._sync_exc = sync_exc
        self.queries = []
        self.submitted = []
        self._job = None

    def query(self, *, endpoint, adql, maxrec=10_000):
        self.queries.append(adql)
        if self._sync_exc:
            raise self._sync_exc
        return self._sync_table

    def submit_async(self, *, endpoint, adql, maxrec=10_000):
        self.submitted.append(adql)
        return "http://x/async/job/1"

    def load_job(self, job_url):
        return self._job


class _FakeJob:
    def __init__(self, phases, table=None):
        self._phases = list(phases)
        self._table = table

    @property
    def phase(self):
        return self._phases.pop(0) if len(self._phases) > 1 else self._phases[0]

    def raise_if_error(self):
        pass

    def fetch_result(self):
        class _R:
            def __init__(self, t):
                self._t = t

            def to_table(self):
                return self._t

        return _R(self._table)


@pytest.fixture
def one_optical(monkeypatch):
    archives = (_archive("datalab", waveband="optical", geom=Q3CRadial("ra", "dec"), priority=1),)
    monkeypatch.setattr(sel, "active_archives", lambda: archives)
    return archives


def test_sync_count_returns_integer(one_optical, monkeypatch):
    tap = _FakeTap(sync_table=Table({"n": [842]}))
    monkeypatch.setattr(count_mod, "_get_tap", lambda: tap)
    monkeypatch.setattr(
        sel, "get_resolver", lambda: type("R", (), {"resolve": lambda s, n: (187.7, 12.4)})()
    )

    out = count_mod.vo_count_observations(target="M87", waveband="optical")

    assert out["count"] == 842
    assert out["status"] == "ok"
    assert out["plan"]["chosen_archive"] == "datalab"
    assert "q3c_radial_query" in out["plan"]["adql"]
    assert out["resolved"]["ra"] == pytest.approx(187.7)


def test_literal_coords_skip_resolver(one_optical, monkeypatch):
    tap = _FakeTap(sync_table=Table({"n": [5]}))
    monkeypatch.setattr(count_mod, "_get_tap", lambda: tap)
    monkeypatch.setattr(
        sel,
        "get_resolver",
        lambda: type("R", (), {"resolve": lambda s, n: (_ for _ in ()).throw(AssertionError())})(),
    )
    out = count_mod.vo_count_observations(target="187.7 12.4", waveband="optical")
    assert out["count"] == 5


def test_unresolvable_soft_fails(one_optical, monkeypatch):
    monkeypatch.setattr(count_mod, "_get_tap", lambda: _FakeTap(sync_table=Table({"n": [0]})))
    monkeypatch.setattr(
        sel, "get_resolver", lambda: type("R", (), {"resolve": lambda s, n: None})()
    )
    out = count_mod.vo_count_observations(target="XYZZY", waveband="optical")
    assert out["resolved"] is False


def test_no_countable_archive_soft_fails(monkeypatch):
    monkeypatch.setattr(sel, "active_archives", lambda: ())
    monkeypatch.setattr(
        sel, "get_resolver", lambda: type("R", (), {"resolve": lambda s, n: (1.0, 2.0)})()
    )
    out = count_mod.vo_count_observations(target="M87")
    assert out["count"] == 0
    assert "hint" in out


def test_async_completes_within_budget(monkeypatch):
    archives = (
        _archive("nrao", waveband="radio", mode="async", geom=ContainsPoint("s_ra", "s_dec")),
    )
    monkeypatch.setattr(sel, "active_archives", lambda: archives)
    monkeypatch.setattr(
        sel, "get_resolver", lambda: type("R", (), {"resolve": lambda s, n: (200.0, 20.0)})()
    )
    tap = _FakeTap()
    tap._job = _FakeJob(["EXECUTING", "COMPLETED"], table=Table({"n": [17]}))
    monkeypatch.setattr(count_mod, "_get_tap", lambda: tap)
    monkeypatch.setattr(count_mod, "_sleep", lambda s: None)

    out = count_mod.vo_count_observations(target="200.0 20.0", waveband="radio")
    assert out["count"] == 17
    assert tap.submitted  # went async


def test_async_budget_exhausted_returns_pending(monkeypatch):
    archives = (
        _archive("nrao", waveband="radio", mode="async", geom=ContainsPoint("s_ra", "s_dec")),
    )
    monkeypatch.setattr(sel, "active_archives", lambda: archives)
    monkeypatch.setattr(
        sel, "get_resolver", lambda: type("R", (), {"resolve": lambda s, n: (200.0, 20.0)})()
    )
    tap = _FakeTap()
    tap._job = _FakeJob(["EXECUTING"], table=None)
    monkeypatch.setattr(count_mod, "_get_tap", lambda: tap)
    monkeypatch.setattr(count_mod, "_sleep", lambda s: None)
    # shrink the budget so the loop exits fast
    from manna.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("MANNA_COUNT_ASYNC_BUDGET_SECONDS", "2")
    try:
        out = count_mod.vo_count_observations(target="200.0 20.0", waveband="radio")
        assert out["status"] == "pending"
        assert out["count"] is None
        assert out["job_url"].startswith("http")
        assert "next_steps" in out
    finally:
        get_settings.cache_clear()
