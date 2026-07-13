"""Offline unit tests for the archive-caveat regression logic (evals/caveats.py).

No network: the live probe (`_probe`) is monkeypatched, so these exercise the verdict
routing — including the STALE-vs-UNREACHABLE hardening — deterministically.
"""

from __future__ import annotations

import pytest

from evals import caveats
from evals.caveats import Caveat, _has_cols, _has_table, _verdict, check_caveat


# --------------------------------------------------------------------------- #
# _verdict — the ok/error/empty/nonempty routing + service-error handling
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "expect,outcome,n_rows,want",
    [
        # success-expecting caveats
        ("ok", "ok", 1, "still_true"),
        ("ok", "query_error", 0, "stale"),  # semantic reject → real drift
        ("ok", "service_error", 0, "unreachable"),  # transient → can't judge
        # error-expecting caveats: any failure confirms; success is the drift
        ("error", "query_error", 0, "still_true"),  # e.g. datalab CONTAINS reject
        ("error", "service_error", 0, "still_true"),  # e.g. NRAO sync 5xx (a service error!)
        ("error", "ok", 1, "stale"),  # the failure went away
        # absence (empty)
        ("empty", "ok", 0, "still_true"),
        ("empty", "ok", 3, "stale"),  # the thing we said was absent is present
        ("empty", "query_error", 0, "stale"),
        ("empty", "service_error", 0, "unreachable"),
        # presence (nonempty)
        ("nonempty", "ok", 2, "still_true"),
        ("nonempty", "ok", 0, "stale"),
        ("nonempty", "query_error", 0, "stale"),
        ("nonempty", "service_error", 0, "unreachable"),
    ],
)
def test_verdict_routing(expect, outcome, n_rows, want):
    assert _verdict(expect, outcome, n_rows) == want


def test_verdict_unknown_expect_raises():
    with pytest.raises(ValueError):
        _verdict("bogus", "ok", 0)


# --------------------------------------------------------------------------- #
# query builders
# --------------------------------------------------------------------------- #
def test_has_table_sql():
    assert _has_table("nsc_dr2.object") == (
        "SELECT table_name FROM tap_schema.tables WHERE table_name = 'nsc_dr2.object'"
    )


def test_has_cols_sql_quotes_and_joins():
    sql = _has_cols("tap_schema.obscore", ("instrument_name", "facility_name"))
    assert "table_name = 'tap_schema.obscore'" in sql
    assert "column_name IN ('instrument_name', 'facility_name')" in sql


# --------------------------------------------------------------------------- #
# check_caveat — manual / no-endpoint / control-gate, no network
# --------------------------------------------------------------------------- #
def test_manual_caveat_never_probes():
    cv = caveats._manual("nrao", "lower-upper-fail", "LOWER()/UPPER() fail", "src")
    row = check_caveat(cv, control_ok=True)
    assert row["status"] == "manual"
    assert "verify by hand" in row["detail"]


def test_control_failed_is_unreachable_not_stale():
    cv = Caveat("datalab", "x", "claim", "ok", "SELECT 1")
    row = check_caveat(cv, control_ok=False)
    assert row["status"] == "unreachable"
    assert "control probe failed" in row["detail"]


def test_unknown_archive_is_unreachable():
    cv = Caveat("nope", "x", "claim", "ok", "SELECT 1")
    row = check_caveat(cv, control_ok=True)
    assert row["status"] == "unreachable"


# --------------------------------------------------------------------------- #
# check_caveat count path — monkeypatch the probe to canned outcomes
# --------------------------------------------------------------------------- #
def _patch_probe(monkeypatch, outcome, n_rows, vals):
    monkeypatch.setattr(caveats, "_probe", lambda *a, **k: (outcome, n_rows, vals, ""))


def test_count_all_present_still_true(monkeypatch):
    cols = ("instrument_name", "facility_name")
    _patch_probe(monkeypatch, "ok", 2, list(cols))
    cv = caveats._cols("nrao", "tap_schema.obscore", "instr", "claim", cols, "src")
    row = check_caveat(cv, control_ok=True)
    assert row["status"] == "still_true"


def test_count_missing_column_is_stale_and_named(monkeypatch):
    cols = ("instrument_name", "facility_name")
    _patch_probe(monkeypatch, "ok", 1, ["instrument_name"])  # facility_name dropped
    cv = caveats._cols("nrao", "tap_schema.obscore", "instr", "claim", cols, "src")
    row = check_caveat(cv, control_ok=True)
    assert row["status"] == "stale"
    assert "facility_name" in row["detail"]
    assert "instrument_name" not in row["detail"]  # the surviving one isn't reported missing


def test_count_service_error_is_unreachable(monkeypatch):
    cols = ("a", "b")
    _patch_probe(monkeypatch, "service_error", 0, [])
    cv = caveats._cols("nrao", "tap_schema.obscore", "x", "claim", cols, "src")
    row = check_caveat(cv, control_ok=True)
    assert row["status"] == "unreachable"


# --------------------------------------------------------------------------- #
# the shipped CAVEATS table stays well-formed
# --------------------------------------------------------------------------- #
def test_caveat_ids_unique_per_archive():
    seen: set[tuple[str, str]] = set()
    for cv in caveats.CAVEATS:
        key = (cv.archive, cv.caveat_id)
        assert key not in seen, f"duplicate caveat id {key}"
        seen.add(key)


def test_every_caveat_has_a_known_expect():
    valid = {"ok", "error", "empty", "nonempty", "count", "manual"}
    for cv in caveats.CAVEATS:
        assert cv.expect in valid, f"{cv.caveat_id}: {cv.expect}"
        if cv.expect == "count":
            assert cv.columns, f"{cv.caveat_id}: count caveat needs columns"
        if cv.expect != "manual":
            assert cv.adql, f"{cv.caveat_id}: probeable caveat needs adql"
