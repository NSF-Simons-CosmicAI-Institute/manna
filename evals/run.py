"""CLI: run the eval suite against the model under test and report metrics.

Examples:
    # validate the task suite without calling any model
    uv run python -m evals.run --dry-run

    # run tiers 1-2 against the dlai01 Qwen3.5 (reads ANTHROPIC_* / EVAL_MODEL_* env)
    uv run python -m evals.run --tier 1 --tier 2

    # run the tier-3 ablation (each trap task runs with AND without curated context)
    uv run python -m evals.run --tier 3

    # full suite, with hosted Claude as the rubric judge
    EVAL_JUDGE_NAME=claude-opus-4-8 uv run python -m evals.run

Tier-3 tasks (and anything under --condition both) run twice — full vs. ablated
context — and the report prints the trap-avoidance delta, the server's headline ROI.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from evals.harness import ModelConfig, TaskRun, run_task
from evals.score import TaskScore, load_tasks, score_task

RESULTS_DIR = Path(__file__).with_name("results")


def _conditions_for(task: dict[str, Any], cli: str) -> list[str]:
    if cli in ("full", "ablated"):
        return [cli]
    if cli == "both" or task.get("tier") == 3:
        return ["full", "ablated"]
    return ["full"]


async def _run_one(
    task: dict[str, Any],
    condition: str,
    cfg: ModelConfig,
    judge: ModelConfig | None,
    sem: asyncio.Semaphore,
) -> tuple[TaskRun, TaskScore]:
    async with sem:
        run = await run_task(task, cfg, condition)
    score = await score_task(task, run, judge)
    status = "PASS" if score.passed else "FAIL"
    unscored = " (has unscored checks)" if score.has_unscored else ""
    print(f"  [{status}] {task['id']} [{condition}]{unscored}")
    return run, score


def _judge_from_env() -> ModelConfig | None:
    import os

    if not (os.getenv("EVAL_JUDGE_NAME") or os.getenv("EVAL_JUDGE_BASE_URL")):
        return None
    return ModelConfig.from_env(prefix="EVAL_JUDGE")


def _summarize(scores: list[TaskScore]) -> dict[str, Any]:
    def rate(items: list[TaskScore]) -> float | None:
        graded = [s for s in items if any(v is not None for v in s.checks.values())]
        return round(sum(s.passed for s in graded) / len(graded), 3) if graded else None

    by_tier = {t: [s for s in scores if s.tier == t] for t in sorted({s.tier for s in scores})}
    summary: dict[str, Any] = {
        "overall_pass_rate": rate(scores),
        "by_tier": {f"tier{t}": rate(v) for t, v in by_tier.items()},
    }

    # Tier-3 headline: trap-avoidance full vs. ablated + per-trap breakdown.
    tier3 = [s for s in scores if s.tier == 3]
    if tier3:
        full = [s for s in tier3 if s.condition == "full"]
        ablated = [s for s in tier3 if s.condition == "ablated"]
        by_task: dict[str, dict[str, bool]] = {}
        for s in tier3:
            by_task.setdefault(s.task_id, {})[s.condition] = s.passed
        summary["tier3_ablation"] = {
            "avoidance_with_context": rate(full),
            "avoidance_without_context": rate(ablated),
            "per_trap": by_task,
        }
    return summary


def _print_report(summary: dict[str, Any], runs: list[TaskRun]) -> None:
    print("\n" + "=" * 60)
    print("EVAL SUMMARY")
    print("=" * 60)
    print(f"Overall pass rate : {summary['overall_pass_rate']}")
    for tier, r in summary["by_tier"].items():
        print(f"  {tier} pass rate  : {r}")
    if "tier3_ablation" in summary:
        ab = summary["tier3_ablation"]
        print("\nTier-3 trap avoidance (the server's ROI):")
        print(f"  WITH curated context    : {ab['avoidance_with_context']}")
        print(f"  WITHOUT curated context : {ab['avoidance_without_context']}")
        print("  per trap (full / ablated):")
        for tid, conds in ab["per_trap"].items():
            f = "PASS" if conds.get("full") else "FAIL"
            a = "PASS" if conds.get("ablated") else "FAIL"
            print(f"    {tid:24s} {f:4s} / {a}")
    ok_runs = [r for r in runs if not r.error]
    if ok_runs:
        avg_calls = sum(r.num_tool_calls for r in ok_runs) / len(ok_runs)
        avg_lat = sum(r.latency_s for r in ok_runs) / len(ok_runs)
        tot_out = sum(r.output_tokens for r in ok_runs)
        print(
            f"\nEfficiency: {avg_calls:.1f} tool-calls/task, "
            f"{avg_lat:.1f}s/task, {tot_out} output tokens total"
        )
    errored = [r for r in runs if r.error]
    if errored:
        print(f"\nHarness errors ({len(errored)}):")
        for r in errored:
            print(f"  {r.task_id} [{r.condition}]: {r.error}")


async def _main_async(args: argparse.Namespace) -> int:
    tiers = args.tier or [1, 2, 3, 4]
    tasks = [t for t in load_tasks() if t["tier"] in tiers]
    if args.task:
        wanted = set(args.task)
        tasks = [t for t in tasks if t["id"] in wanted]
    if not tasks:
        print("No tasks matched the filters.")
        return 1

    if args.dry_run:
        print(f"Loaded {len(tasks)} task(s). Conditions per task:")
        for t in tasks:
            conds = _conditions_for(t, args.condition)
            print(f"  {t['id']:24s} tier {t['tier']}  -> {', '.join(conds)}")
        print("\ntasks.yaml validated OK (no model calls made).")
        return 0

    cfg = ModelConfig.from_env()
    judge = _judge_from_env()
    print(f"Model under test : {cfg.label}  (base_url={cfg.base_url or 'hosted'})")
    print(f"Judge            : {judge.label if judge else 'none (rubric tasks unscored)'}")
    print(f"Running {len(tasks)} task(s), concurrency={args.concurrency}\n")

    sem = asyncio.Semaphore(args.concurrency)
    coros = [
        _run_one(t, cond, cfg, judge, sem)
        for t in tasks
        for cond in _conditions_for(t, args.condition)
    ]
    results = await asyncio.gather(*coros)
    runs = [r for r, _ in results]
    scores = [s for _, s in results]

    summary = _summarize(scores)
    _print_report(summary, runs)

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    out = RESULTS_DIR / f"{stamp}.json"
    out.write_text(
        json.dumps(
            {
                "model": cfg.label,
                "summary": summary,
                "scores": [s.to_dict() for s in scores],
                "runs": [r.to_dict() for r in runs],
            },
            indent=2,
            default=str,
        )
    )
    print(f"\nWrote {out}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Run the astro-archives-mcp agentic eval.")
    p.add_argument(
        "--tier",
        type=int,
        action="append",
        choices=[1, 2, 3, 4],
        help="restrict to tier(s); repeatable. Default: all.",
    )
    p.add_argument("--task", action="append", help="restrict to task id(s); repeatable.")
    p.add_argument(
        "--condition",
        choices=["auto", "full", "ablated", "both"],
        default="auto",
        help="context condition. auto = both for tier 3, full otherwise.",
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="max concurrent tasks (keep low for a single-GPU model).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="validate tasks.yaml and print the plan without calling any model.",
    )
    args = p.parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
