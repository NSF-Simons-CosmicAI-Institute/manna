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


async def _main(path: Path) -> int:
    data = json.loads(path.read_text())
    tasks = {t["id"]: t for t in load_tasks()}
    judge = ModelConfig.from_env(prefix="EVAL_JUDGE")
    print(f"Re-judging {path.name} with judge: {judge.label}\n")

    verdicts = []
    for run in data.get("runs", []):
        task = tasks.get(run["task_id"])
        if not task or not task.get("rubric"):
            continue
        tr = _reconstruct(run)
        passed, quality, reason = await score_rubric(task, tr, judge)
        verdicts.append((run["task_id"], run.get("condition", "full"), passed, quality))
        mark = "PASS" if passed else ("FAIL" if passed is not None else "????")
        print(f"  [{mark}] q={quality} {run['task_id']} [{run.get('condition')}]")
        print(f"         {reason}")

    graded = [v for v in verdicts if v[2] is not None]
    if graded:
        rate = sum(v[2] for v in graded) / len(graded)
        print(f"\nRubric pass rate ({judge.label}): {rate:.3f}  ({len(graded)} tasks judged)")
    else:
        print("\nNo rubric tasks judged (empty or unparseable).")
    return 0


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m evals.rejudge <results.json>")
        return 2
    return asyncio.run(_main(Path(sys.argv[1])))


if __name__ == "__main__":
    raise SystemExit(main())
