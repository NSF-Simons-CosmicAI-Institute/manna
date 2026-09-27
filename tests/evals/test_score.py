"""Offline unit tests for the scoring logic (evals/score.py)."""

from __future__ import annotations

import pytest

from evals.harness import TaskRun, ToolCall
from evals.score import (
    _apply_op,
    _check_calls,
    _extract_verdict,
    _ground_truth_ok,
    _leaked,
    _tools_in_order,
    score_programmatic,
)


def _run(trace=(), answer="", error=None):
    r = TaskRun("t", 1, "full", "m")
    r.trace = [ToolCall(t, a, res, err) for t, a, res, err in trace]
    r.final_answer = answer
    r.error = error
    return r


# --------------------------------------------------------------------------- #
# _extract_verdict — tolerate reasoning preambles / markdown / trailing prose
# --------------------------------------------------------------------------- #
def test_extract_verdict_clean_json():
    assert _extract_verdict('{"pass": true, "quality": 5, "reason": "ok"}')["pass"] is True


def test_extract_verdict_with_reasoning_preamble():
    text = 'Thinking Process: the answer looks right.\n{"pass": false, "quality": 2, "reason": "x"}'
    v = _extract_verdict(text)
    assert v["pass"] is False
    assert v["quality"] == 2


def test_extract_verdict_last_object_with_pass_wins():
    text = '{"note": "ignore me"} then {"pass": true, "quality": 4}'
    assert _extract_verdict(text)["pass"] is True


def test_extract_verdict_none_when_unparseable():
    assert _extract_verdict("no json here at all") is None
    assert _extract_verdict('{"quality": 5}') is None  # no "pass" key


# --------------------------------------------------------------------------- #
# _apply_op — the arg-check primitive
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "value,check,want",
    [
        ("async", {"op": "contains", "value": "syn"}, True),
        ("async", {"op": "not_contains", "value": "CONTAINS("}, True),
        ("ASYNC", {"op": "icontains", "value": "async"}, True),
        ("async", {"op": "equals", "value": "async"}, True),
        ("Async", {"op": "iequals", "value": "async"}, True),
        ("mode=async", {"op": "regex", "value": r"mode=\w+"}, True),
        (5.0, {"op": "near", "value": 5.01, "tol": 0.05}, True),
        (5.0, {"op": "near", "value": 5.5, "tol": 0.05}, False),
        (10, {"op": "gte", "value": 5}, True),
        (3, {"op": "lte", "value": 5}, True),
        ("x", {"op": "present"}, True),
        (None, {"op": "present"}, False),
        (None, {"op": "not_contains", "value": "z"}, True),  # missing arg satisfies negatives
        (None, {"op": "contains", "value": "z"}, False),  # ...and fails positives
    ],
)
def test_apply_op(value, check, want):
    assert _apply_op(value, check) is want


def test_apply_op_unknown_raises():
    with pytest.raises(ValueError):
        _apply_op("x", {"op": "sideways"})


# --------------------------------------------------------------------------- #
# _check_calls — any/all across multiple calls to a tool
# --------------------------------------------------------------------------- #
def test_check_calls_match_any_vs_all():
    calls = [{"args": {"mode": "sync"}}, {"args": {"mode": "async"}}]
    assert _check_calls(calls, {"arg": "mode", "op": "equals", "value": "async", "match": "any"})
    assert not _check_calls(
        calls, {"arg": "mode", "op": "equals", "value": "async", "match": "all"}
    )


def test_check_calls_empty_is_false():
    assert not _check_calls([], {"arg": "mode", "op": "present"})


# --------------------------------------------------------------------------- #
# _tools_in_order — expected tools as a subsequence
# --------------------------------------------------------------------------- #
def test_tools_in_order_subsequence():
    actual = ["resolve_target_name", "describe_table", "run_adql_query"]
    assert _tools_in_order(actual, ["resolve_target_name", "run_adql_query"])
    assert not _tools_in_order(actual, ["run_adql_query", "resolve_target_name"])


# --------------------------------------------------------------------------- #
# _ground_truth_ok
# --------------------------------------------------------------------------- #
def test_ground_truth_coords_within_tol():
    gt = {"type": "coords", "ra": 187.7059, "dec": 12.3911, "tol_deg": 0.01}
    assert _ground_truth_ok(gt, "M87 is at RA 187.7059, Dec 12.3911 (ICRS).")
    assert not _ground_truth_ok(gt, "RA 10.0, Dec 20.0")


def test_ground_truth_contains_and_regex_and_nonempty():
    assert _ground_truth_ok(
        {"type": "contains", "values": ["EVLA", "GBT"]}, "instruments: evla, gbt"
    )
    assert not _ground_truth_ok({"type": "contains", "values": ["VLBA"]}, "only evla here")
    assert _ground_truth_ok({"type": "regex", "pattern": r"\d+ objects"}, "found 42 objects")
    assert _ground_truth_ok({"type": "nonempty"}, "anything")
    assert not _ground_truth_ok({"type": "nonempty"}, "   ")


# --------------------------------------------------------------------------- #
# _leaked — the redaction invariant
# --------------------------------------------------------------------------- #
def test_leaked_detects_bearer_token_in_result():
    run = _run(trace=[("run_adql_query", {}, {"msg": "Authorization: Bearer sk-secret"}, False)])
    assert _leaked(run) == "Bearer "


def test_leaked_none_when_clean():
    run = _run(trace=[("run_adql_query", {}, {"rows": 3}, False)])
    assert _leaked(run) is None


# --------------------------------------------------------------------------- #
# score_programmatic — the check aggregation
# --------------------------------------------------------------------------- #
def test_score_programmatic_expect_and_forbid_and_leak():
    task = {
        "id": "t",
        "tier": 1,
        "expect_tools": ["resolve_target_name"],
        "forbid_tools": ["abort_async_job"],
    }
    run = _run(trace=[("resolve_target_name", {}, {"ra": 1}, False)], answer="done")
    score = score_programmatic(task, run)
    assert score.checks["expect_tools"] is True
    assert score.checks["forbid_tools"] is True
    assert score.checks["no_leak"] is True
    assert score.passed


def test_score_programmatic_arg_check_and_ground_truth():
    task = {
        "id": "t",
        "tier": 2,
        "arg_checks": {"run_adql_query": [{"arg": "mode", "op": "equals", "value": "async"}]},
        "ground_truth": {"type": "contains", "values": ["42"]},
    }
    good = _run(trace=[("run_adql_query", {"mode": "async"}, {}, False)], answer="the answer is 42")
    s = score_programmatic(task, good)
    assert s.checks["args:run_adql_query"] is True
    assert s.checks["ground_truth"] is True

    bad = _run(trace=[("run_adql_query", {"mode": "sync"}, {}, False)], answer="no number")
    s2 = score_programmatic(task, bad)
    assert s2.checks["args:run_adql_query"] is False
    assert s2.checks["ground_truth"] is False


def test_score_programmatic_leak_fails_and_notes():
    task = {"id": "t", "tier": 4}
    run = _run(trace=[("run_adql_query", {}, "Traceback (most recent call last): boom", False)])
    s = score_programmatic(task, run)
    assert s.checks["no_leak"] is False
    assert any("LEAK" in n for n in s.notes)
    assert not s.passed


def test_score_programmatic_expect_any_of_accepts_grouped_alternatives():
    """A nested list inside expect_any_of is an all-of group: the check passes when
    any group (or bare tool name) is fully present in the trace. This is how a task
    accepts either the primitive tool chain or a workflow tool that bundles it."""
    task = {
        "id": "t",
        "tier": 2,
        "expect_any_of": [
            ["resolve_target_name", "search_catalog_by_position"],
            ["resolve_target_name", "run_adql_query"],
            "find_observations_of_target",
        ],
    }
    primitive = _run(
        trace=[("resolve_target_name", {}, {}, False), ("run_adql_query", {}, {}, False)]
    )
    assert score_programmatic(task, primitive).checks["expect_any_of"] is True

    workflow = _run(trace=[("find_observations_of_target", {}, {}, False)])
    assert score_programmatic(task, workflow).checks["expect_any_of"] is True

    half_group = _run(trace=[("run_adql_query", {}, {}, False)])
    assert score_programmatic(task, half_group).checks["expect_any_of"] is False
