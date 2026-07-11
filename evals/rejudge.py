"""Re-score the rubric tasks in a saved results file with a judge model.

Decouples judging from the (expensive) agent loop: the model-under-test answers
are reused from disk, so you can apply different judges to the *same* answers —
e.g. the model itself (zero Anthropic cost) vs. hosted Claude — and compare.

    # judge with whatever EVAL_JUDGE_* points at
    EVAL_JUDGE_NAME=... uv run python -m evals.rejudge evals/results/<file>.json

The judge config is read from EVAL_JUDGE_* (falling back to ANTHROPIC_*); see
ModelConfig.from_env. Only tasks that declare a `rubric` are judged.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from evals.harness import ModelConfig, TaskRun, ToolCall
from evals.score import load_tasks, score_rubric


def _reconstruct(run: dict) -> TaskRun:
    r = TaskRun(
        task_id=run["task_id"],
        tier=run["tier"],
        condition=run.get("condition", "full"),
        model=run.get("model", "?"),
    )
    r.final_answer = run.get("final_answer", "")
    r.trace = [
        ToolCall(c["tool"], c.get("args", {}), c.get("result"), c.get("is_error", False))
        for c in run.get("trace", [])
    ]
    return r


async def _main(path: Path, tasks_path: Path | None = None) -> int:
    data = json.loads(path.read_text())
    tasks = {t["id"]: t for t in load_tasks(tasks_path)}
    judge = ModelConfig.from_env(prefix="EVAL_JUDGE")
    print(f"Re-judging {path.name} with judge: {judge.label}\n")

    verdicts = []  # (group, task_id, passed)
    for run in data.get("runs", []):
        task = tasks.get(run["task_id"])
        if not task or not task.get("rubric"):
            continue
        group = run.get("arm") or run.get("condition", "full")  # arms (mcp_quality) or full/ablated
        tr = _reconstruct(run)
        passed, quality, reason = await score_rubric(task, tr, judge)
        verdicts.append((group, run["task_id"], passed))
        mark = "PASS" if passed else ("FAIL" if passed is not None else "????")
        print(f"  [{mark}] q={quality} {group:8s} {run['task_id']}")
        print(f"         {reason}")

    groups = sorted({g for g, _, _ in verdicts})
    print(f"\nRubric pass rate ({judge.label}):")
    for g in groups:
        graded = [p for gr, _, p in verdicts if gr == g and p is not None]
        rate = f"{sum(graded) / len(graded):.3f}" if graded else "n/a"
        print(f"  {g:10s} {rate}  ({len(graded)} judged)")
    return 0


def main() -> int:
    from evals._env import load_env

    load_env()
    if len(sys.argv) not in (2, 4) or (len(sys.argv) == 4 and sys.argv[2] != "--tasks"):
        print("usage: python -m evals.rejudge <results.json> [--tasks <tasks.yaml>]")
        return 2
    tasks_path = Path(sys.argv[3]) if len(sys.argv) == 4 else None
    return asyncio.run(_main(Path(sys.argv[1]), tasks_path))


if __name__ == "__main__":
    raise SystemExit(main())
