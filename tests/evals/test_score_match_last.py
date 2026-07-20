"""`match: last` — score where the model ENDED UP, not every step it took.

Needed for loud traps (issue #57). Their guidance rides the error `hint`, which
is reactive by construction: the model must trip the trap once to be told about
it. `match: all` therefore scores such a task FAIL however well the hint works,
which measures prevention, not recovery. `match: last` asks the question the
hint channel can actually answer — did the model end on a good query?
"""

from __future__ import annotations

import pytest

from evals.harness import TaskRun, ToolCall
from evals.score import _check_calls, load_tasks, score_programmatic

CHECK = {"arg": "adql", "op": "not_icontains", "value": "LOWER(", "match": "last"}


def _calls(*adqls):
    return [{"args": {"adql": a}} for a in adqls]


def test_last_ignores_earlier_violations():
    """Trip the trap, read the hint, recover -> pass."""
    assert _check_calls(_calls("SELECT LOWER(x)", "SELECT x"), CHECK) is True


def test_last_fails_when_the_final_call_still_violates():
    """Never recovered, or regressed at the end -> fail."""
    assert _check_calls(_calls("SELECT x", "SELECT LOWER(x)"), CHECK) is False


def test_last_on_a_single_clean_call_passes():
    assert _check_calls(_calls("SELECT x"), CHECK) is True


def test_last_with_no_calls_fails():
    """Consistent with the other policies: nothing to score is not a pass."""
    assert _check_calls([], CHECK) is False


def test_all_and_any_are_unchanged():
    calls = _calls("SELECT LOWER(x)", "SELECT x")
    assert _check_calls(calls, {**CHECK, "match": "all"}) is False
    assert _check_calls(calls, {**CHECK, "match": "any"}) is True


def test_unknown_match_policy_is_rejected():
    """A typo'd policy must not silently degrade to 'any' and fake a pass."""
    with pytest.raises(ValueError, match="unknown arg-check match"):
        _check_calls(_calls("SELECT x"), {**CHECK, "match": "lsat"})


# ---------- the shipped task ----------


def _run(*adqls) -> TaskRun:
    r = TaskRun("t", 3, "full", "m")
    r.trace = [ToolCall("vo_tap_query", {"adql": a}, {}, False) for a in adqls]
    r.final_answer = "done"
    return r


def _task(task_id: str) -> dict:
    return next(t for t in load_tasks() if t["id"] == task_id)


def test_recovery_task_scores_the_hint_channel():
    task = _task("t3-nrao-lowerupper-recovery")
    recovered = _run(
        "SELECT TOP 10 * FROM tap_schema.obscore WHERE LOWER(target_name) = 'm87'",
        "SELECT TOP 10 * FROM tap_schema.obscore WHERE target_name = 'M87'",
    )
    assert score_programmatic(task, recovered).checks["args:vo_tap_query"] is True

    stuck = _run(
        "SELECT TOP 10 * FROM tap_schema.obscore WHERE LOWER(target_name) = 'm87'",
        "SELECT TOP 10 * FROM tap_schema.obscore WHERE LOWER(target_name) LIKE '%m87%'",
    )
    assert score_programmatic(task, stuck).checks["args:vo_tap_query"] is False


def test_prevention_task_still_demands_never_tripping_it():
    """t3-nrao-lowerupper keeps measuring PREVENTION. It is expected to fail
    while the trap is served only reactively — that honesty is the point, and
    it is what would flip if the note ever moved into the description."""
    task = _task("t3-nrao-lowerupper")
    recovered = _run(
        "SELECT TOP 10 * FROM tap_schema.obscore WHERE LOWER(target_name) = 'm87'",
        "SELECT TOP 10 * FROM tap_schema.obscore WHERE target_name = 'M87'",
    )
    assert score_programmatic(task, recovered).checks["args:vo_tap_query"] is False
