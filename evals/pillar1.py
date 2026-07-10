"""Pillar 1 — MCP quality: does the server make workflows easier, cheaper, more accurate?

Runs the deterministic pillar1_tasks.yaml under all three arms and reports the lift:

    full MCP  vs  raw TAP (run_adql only)  vs  raw web (http_get only)

For each arm: success rate (deterministic ground-truth), mean iterations (steps +
tool-calls), mean tokens, mean latency, and tool-error rate. The gap between 'mcp' and
the raw arms is the server's value, in the currency you care about.

    # with model creds sourced (e.g. deploy/frontend/.env for dlai01 Qwen3.5)
    uv run python -m evals.pillar1                # N=1 per (arm, task)
    uv run python -m evals.pillar1 --n 3          # 3 reps for stability
    uv run python -m evals.pillar1 --arm mcp --arm raw_tap
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from evals.harness import ModelConfig, TaskRun, run_task
from evals.score import load_tasks, score_programmatic

ARMS = ["mcp", "raw_tap", "raw_web"]
TASKS_PATH = Path(__file__).with_name("pillar1_tasks.yaml")
RESULTS_DIR = Path(__file__).with_name("results")


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _aggregate(arm: str, runs: list[TaskRun], passes: list[bool]) -> dict[str, Any]:
    ok = [r for r in runs if not r.error]
    return {
        "arm": arm,
        "n": len(runs),
        "success_rate": round(sum(passes) / len(passes), 3) if passes else None,
        "mean_tool_calls": round(_mean([r.num_tool_calls for r in runs]), 2),
        "mean_steps": round(_mean([r.steps for r in runs]), 2),
        "mean_input_tokens": round(_mean([r.input_tokens for r in ok])),
        "mean_output_tokens": round(_mean([r.output_tokens for r in ok])),
        "mean_latency_s": round(_mean([r.latency_s for r in ok]), 1),
        "tool_error_calls": sum(c.is_error for r in runs for c in r.trace),
    }


async def _main(args: argparse.Namespace) -> int:
    cfg = ModelConfig.from_env()
    tasks = load_tasks(TASKS_PATH)
    arms = args.arm or ARMS
    print(f"Model: {cfg.label}  |  arms: {', '.join(arms)}  |  N={args.n}  |  {len(tasks)} tasks\n")

    sem = asyncio.Semaphore(args.concurrency)

    async def one(arm: str, task: dict[str, Any]) -> tuple[str, TaskRun, bool]:
        async with sem:
            try:
                run = await run_task(task, cfg, "full", arm=arm)
            except Exception as exc:
                run = TaskRun(task["id"], task["tier"], "full", cfg.label, arm=arm)
                run.error = f"{type(exc).__name__}: {exc}"
        passed = score_programmatic(task, run).passed
        print(
            f"  [{'PASS' if passed else 'FAIL'}] {arm:8s} {task['id']}"
            f"  ({run.num_tool_calls} calls, {run.input_tokens + run.output_tokens} tok)"
        )
        return arm, run, passed

    jobs = [one(arm, t) for arm in arms for _ in range(args.n) for t in tasks]
    results = await asyncio.gather(*jobs)

    per_arm: dict[str, dict[str, Any]] = {}
    for arm in arms:
        runs = [r for a, r, _ in results if a == arm]
        passes = [p for a, _, p in results if a == arm]
        per_arm[arm] = _aggregate(arm, runs, passes)

    # Report
    print("\n" + "=" * 72)
    print("PILLAR 1 — MCP quality (higher success / lower everything-else is better)")
    print("=" * 72)
    cols = [
        ("success_rate", "success"),
        ("mean_tool_calls", "calls"),
        ("mean_steps", "steps"),
        ("mean_input_tokens", "in-tok"),
        ("mean_output_tokens", "out-tok"),
        ("mean_latency_s", "lat(s)"),
        ("tool_error_calls", "tool-err"),
    ]
    print(f"{'arm':10s}" + "".join(f"{label:>12s}" for _, label in cols))
    for arm in arms:
        a = per_arm[arm]
        print(f"{arm:10s}" + "".join(f"{str(a[key]):>12s}" for key, _ in cols))

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    out = RESULTS_DIR / f"pillar1-{stamp}.json"
    out.write_text(
        json.dumps(
            {
                "model": cfg.label,
                "per_arm": per_arm,
                "runs": [r.to_dict() for _, r, _ in results],
            },
            indent=2,
            default=str,
        )
    )
    print(f"\nWrote {out}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Pillar-1 MCP-quality arm comparison.")
    p.add_argument("--n", type=int, default=1, help="reps per (arm, task)")
    p.add_argument("--arm", action="append", choices=ARMS, help="restrict arms; repeatable")
    p.add_argument("--concurrency", type=int, default=2)
    return asyncio.run(_main(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
