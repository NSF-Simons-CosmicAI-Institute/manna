"""Eval tasks that need a paused archive must declare it and be skipped by default.

nrao ships paused, so running its tasks against a default server would either
hammer the endpoint we agreed to leave alone or fail for a reason that has
nothing to do with MANNA. `requires_archive` makes the dependency explicit and
`partition_by_archive` honours the active set.
"""

import re

from evals.score import load_tasks, partition_by_archive

_NRAO = re.compile(r"\bnrao\b|tap_schema\.obscore", re.IGNORECASE)


def _all_tasks():
    from evals.mcp_quality import TASKS_PATH as MQ_PATH

    return load_tasks() + load_tasks(MQ_PATH)


def test_every_task_that_names_nrao_declares_requires_archive():
    missing = [
        t["id"]
        for t in _all_tasks()
        if _NRAO.search(t.get("prompt", "")) and t.get("requires_archive") != "nrao"
    ]
    assert not missing, f"tasks name NRAO without requires_archive: nrao — {missing}"


def test_partition_skips_nrao_tasks_by_default():
    runnable, skipped = partition_by_archive(_all_tasks())
    assert {name for _, name in skipped} == {"nrao"}
    assert all(t.get("requires_archive") != "nrao" for t in runnable)
    assert len(skipped) >= 15


def test_partition_runs_nrao_tasks_when_active(nrao_active):
    runnable, skipped = partition_by_archive(_all_tasks())
    assert skipped == []
    assert any(t.get("requires_archive") == "nrao" for t in runnable)
