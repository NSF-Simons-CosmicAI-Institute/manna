"""The async-mode arg-checks in the real tasks.yaml must score the OUTCOME.

Post-#55, `mode='auto'` runs sync first and promotes to async on a timeout or an
oversize result — so it reaches NRAO data just as reliably as an explicit
`mode='async'`. Tasks that demanded the literal string 'async' failed traces
that had in fact retrieved the data correctly (issue #58).

These tests pin the loosened checks against the *shipped* tasks.yaml rather than
a synthetic task dict, so a future edit that re-tightens them fails here.
"""

from __future__ import annotations

import pytest

from evals.harness import TaskRun, ToolCall
from evals.score import load_tasks, score_programmatic

# The tier-2/3 tasks whose vo_tap_query mode check gates on the async path.
ASYNC_MODE_TASKS = ("t3-nrao-async", "t2-list-then-query", "t2-schema-bound-query")


def _task(task_id: str) -> dict:
    tasks = {t["id"]: t for t in load_tasks()}
    assert task_id in tasks, f"{task_id} missing from tasks.yaml"
    return tasks[task_id]


# ADQL that satisfies every NON-mode arg-check these tasks carry (the GBT literal
# for t2-schema-bound-query), so the assertions below isolate the mode check.
_ADQL = "SELECT TOP 20 * FROM tap_schema.obscore WHERE instrument_name = 'GBT'"


def _tap_run(*modes: str) -> TaskRun:
    """A run whose vo_tap_query calls used `modes`, in order."""
    r = TaskRun("t", 3, "full", "m")
    r.trace = [ToolCall("vo_tap_query", {"mode": m, "adql": _ADQL}, {}, False) for m in modes]
    r.final_answer = "here are the rows"
    return r


def _args_check(task_id: str, run: TaskRun) -> bool:
    return score_programmatic(_task(task_id), run).checks["args:vo_tap_query"]


@pytest.mark.parametrize("task_id", ASYNC_MODE_TASKS)
@pytest.mark.parametrize("mode", ["async", "auto"])
def test_async_and_auto_both_accepted(task_id: str, mode: str):
    """Both routes to the async path score as avoided — 'auto' auto-promotes."""
    assert _args_check(task_id, _tap_run(mode)) is True


@pytest.mark.parametrize("task_id", ASYNC_MODE_TASKS)
def test_bare_sync_still_rejected(task_id: str):
    """mode='sync' is the actual trap: it 5xxs/times out on obscore reads."""
    assert _args_check(task_id, _tap_run("sync")) is False


@pytest.mark.parametrize("task_id", ASYNC_MODE_TASKS)
def test_sync_retry_loop_still_rejected(task_id: str):
    """match: all — a model that keeps retrying bare sync has not avoided the trap,
    even if one call in the trace used auto."""
    assert _args_check(task_id, _tap_run("auto", "sync", "sync")) is False


def test_mixed_async_and_auto_accepted():
    """A model that starts on auto and escalates to async is fully correct."""
    assert _args_check("t3-nrao-async", _tap_run("auto", "async")) is True
