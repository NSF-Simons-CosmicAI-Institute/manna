"""MCP quality: does the server make workflows easier, cheaper, more accurate?

Runs mcp_quality_tasks.yaml under all three arms and reports the lift:

    full MCP  vs  raw TAP (run_adql only)  vs  raw web (http_get only)

Per arm it reports accuracy (where scorable), completion rate, and efficiency (mean
iterations / tokens / latency / tool-errors). The gap between 'mcp' and the raw arms is
the server's value.

Scoring: tasks with a deterministic `ground_truth` are accuracy-scored now; tasks with
only a `rubric` are accuracy-scored only when a judge is configured (EVAL_JUDGE_*) —
otherwise they count toward COMPLETION + efficiency, and accuracy shows as unscored.

Version-over-version: pass --set-baseline to record the current per-arm metrics, and
future runs auto-diff against `results/mcp-quality-baseline.json` (or --baseline PATH) so
a change to tools/notes visibly moves the numbers.

    uv run python -m evals.mcp_quality --set-baseline       # record a baseline
    uv run python -m evals.mcp_quality --n 3                 # later: auto-diff vs baseline
    EVAL_JUDGE_NAME=... uv run python -m evals.mcp_quality   # activate rubric accuracy
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from evals.harness import ModelConfig, TaskRun, ToolCall, run_task
from evals.score import TaskScore, load_tasks, score_task

ARMS = ["mcp", "raw_tap", "raw_web"]
TASKS_PATH = Path(__file__).with_name("mcp_quality_tasks.yaml")
RESULTS_DIR = Path(__file__).with_name("results")
BASELINE_PATH = RESULTS_DIR / "mcp-quality-baseline.json"

# Metric direction for the diff: which way is "better".
_GOOD_UP = {"accuracy_rate", "completion_rate"}


def _server_version() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parent.parent,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def _judge_from_env() -> ModelConfig | None:
    if not (os.getenv("EVAL_JUDGE_NAME") or os.getenv("EVAL_JUDGE_BASE_URL")):
        return None
    return ModelConfig.from_env(prefix="EVAL_JUDGE")


def _accuracy(score: TaskScore) -> bool | None:
    """Accuracy verdict for a run: ground-truth if present, else judged rubric,
    else None (unscored — no deterministic answer and no judge)."""
    if "ground_truth" in score.checks:
        return score.checks["ground_truth"]
    return score.checks.get("rubric")  # None when no judge / unparseable


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _aggregate(runs: list[TaskRun], accs: list[bool | None]) -> dict[str, Any]:
    ok = [r for r in runs if not r.error]
    scored = [a for a in accs if a is not None]
    completed = [bool(r.final_answer.strip()) and not r.error for r in runs]
    return {
        "n": len(runs),
        "accuracy_rate": round(sum(scored) / len(scored), 3) if scored else None,
        "accuracy_scored_n": len(scored),
        "completion_rate": round(sum(completed) / len(completed), 3) if completed else None,
        "mean_tool_calls": round(_mean([r.num_tool_calls for r in runs]), 2),
        "mean_steps": round(_mean([r.steps for r in runs]), 2),
        "mean_input_tokens": round(_mean([r.input_tokens for r in ok])),
        "mean_output_tokens": round(_mean([r.output_tokens for r in ok])),
        "mean_latency_s": round(_mean([r.latency_s for r in ok]), 1),
        "tool_error_calls": sum(c.is_error for r in runs for c in r.trace),
    }


_COLS = [
    ("accuracy_rate", "acc"),
    ("completion_rate", "compl"),
    ("mean_tool_calls", "calls"),
    ("mean_steps", "steps"),
    ("mean_input_tokens", "in-tok"),
    ("mean_output_tokens", "out-tok"),
    ("mean_latency_s", "lat(s)"),
    ("tool_error_calls", "tool-err"),
]


def _print_table(per_arm: dict[str, dict[str, Any]], arms: list[str]) -> None:
    print(f"{'arm':10s}" + "".join(f"{label:>11s}" for _, label in _COLS))
    for arm in arms:
        a = per_arm[arm]
        print(f"{arm:10s}" + "".join(f"{str(a[key]):>11s}" for key, _ in _COLS))


def _archive_host_map() -> dict[str, str]:
    """host substring -> archive short_name, from the server's own registry."""
    from astro_archives_mcp.archives._endpoints import host_substring_to_short_name

    return {h.lower(): n for h, n in host_substring_to_short_name().items()}


def _archive_of(call: ToolCall, host_map: dict[str, str]) -> str:
    """Attribute a tool call to an archive: the result's `archive` field if present,
    else infer from a host substring in the args (endpoint/url/access_url)."""
    if isinstance(call.result, dict) and call.result.get("archive"):
        return str(call.result["archive"])
    blob = " ".join(str(v) for v in (call.args or {}).values()).lower()
    for host, name in host_map.items():
        if host in blob:
            return name
    return "—"


def _breakdown(runs: list[TaskRun]) -> dict[str, dict[str, list[int]]]:
    """Per-tool and per-archive [calls, error-calls] for the given (mcp-arm) runs —
    shows where iterations and failures concentrate, i.e. what to refine next."""
    host_map = _archive_host_map()
    by_tool: dict[str, list[int]] = {}
    by_archive: dict[str, list[int]] = {}
    for run in runs:
        for c in run.trace:
            bt = by_tool.setdefault(c.tool, [0, 0])
            bt[0] += 1
            bt[1] += int(c.is_error)
            ba = by_archive.setdefault(_archive_of(c, host_map), [0, 0])
            ba[0] += 1
            ba[1] += int(c.is_error)
    return {"by_tool": by_tool, "by_archive": by_archive}


def _print_breakdown(bd: dict[str, dict[str, list[int]]]) -> None:
    print("\nmcp arm — where calls/errors concentrate (calls / error-calls):")
    for dim, label in (("by_tool", "by tool"), ("by_archive", "by archive")):
        print(f"  {label}:")
        for key, (calls, errs) in sorted(bd[dim].items(), key=lambda kv: -kv[1][0]):
            flag = "   <-- errors here" if errs else ""
            print(f"    {key:24s} {calls:4d} / {errs:<3d}{flag}")


def _print_diff(
    cur: dict[str, dict], cur_version: str, base: dict, arms: list[str], cur_tasks: list[str]
) -> None:
    base_arms = base.get("per_arm", {})
    print(
        f"\nversion-over-version diff  (baseline {base.get('server_version', '?')} "
        f"→ current {cur_version})"
    )
    base_tasks = base.get("task_ids")
    if base_tasks is not None and set(base_tasks) != set(cur_tasks):
        print(
            f"  ⚠ task suite CHANGED since baseline ({len(base_tasks)} → {len(cur_tasks)} "
            "tasks) — metrics are NOT directly comparable; re-baseline with --set-baseline."
        )
    for arm in arms:
        if arm not in base_arms:
            continue
        print(f"  {arm}:")
        for key, label in _COLS:
            c, b = cur[arm].get(key), base_arms[arm].get(key)
            if c is None or b is None:
                continue
            delta = round(c - b, 3)
            if delta == 0:
                mark = "flat"
            else:
                improved = (delta > 0) == (key in _GOOD_UP)
                mark = "better" if improved else "WORSE"
            sign = "+" if delta >= 0 else ""
            print(f"    {label:9s} {str(b):>9s} -> {str(c):>9s}  ({sign}{delta}) {mark}")


async def _main(args: argparse.Namespace) -> int:
    cfg = ModelConfig.from_env()
    judge = _judge_from_env()
    tasks = load_tasks(TASKS_PATH)
    arms = args.arm or ARMS
    version = _server_version()
    print(f"Model: {cfg.label}  |  server: {version}  |  judge: {judge.label if judge else 'none'}")
    print(f"arms: {', '.join(arms)}  |  N={args.n}  |  {len(tasks)} tasks\n")

    sem = asyncio.Semaphore(args.concurrency)

    async def one(arm: str, task: dict[str, Any]) -> tuple[str, TaskRun, bool | None]:
        async with sem:
            try:
                run = await run_task(task, cfg, "full", arm=arm)
            except Exception as exc:
                run = TaskRun(task["id"], task["tier"], "full", cfg.label, arm=arm)
                run.error = f"{type(exc).__name__}: {exc}"
        acc = _accuracy(await score_task(task, run, judge))
        tag = {True: "PASS", False: "FAIL", None: "····"}[acc]
        print(
            f"  [{tag}] {arm:8s} {task['id']}"
            f"  ({run.num_tool_calls} calls, {run.input_tokens + run.output_tokens} tok)"
        )
        return arm, run, acc

    jobs = [one(arm, t) for arm in arms for _ in range(args.n) for t in tasks]
    results = await asyncio.gather(*jobs)

    per_arm: dict[str, dict[str, Any]] = {}
    for arm in arms:
        runs = [r for a, r, _ in results if a == arm]
        accs = [acc for a, _, acc in results if a == arm]
        per_arm[arm] = _aggregate(runs, accs)

    print("\n" + "=" * 80)
    print("MCP QUALITY — arm comparison (higher acc/compl, lower everything-else is better)")
    print("=" * 80)
    _print_table(per_arm, arms)

    # Per-tool / per-archive breakdown for the mcp arm — what to refine next.
    breakdown = None
    if "mcp" in arms:
        breakdown = _breakdown([r for a, r, _ in results if a == "mcp"])
        _print_breakdown(breakdown)

    # Version-over-version diff.
    baseline_path = Path(args.baseline) if args.baseline else BASELINE_PATH
    if baseline_path.exists():
        _print_diff(
            per_arm, version, json.loads(baseline_path.read_text()), arms, [t["id"] for t in tasks]
        )
    elif not args.set_baseline:
        print(f"\n(no baseline at {baseline_path.name}; run --set-baseline to record one)")

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    record = {
        "server_version": version,
        "model": cfg.label,
        "timestamp": stamp,
        "per_arm": {a: per_arm[a] for a in arms},
        "task_ids": [t["id"] for t in tasks],
        "mcp_breakdown": breakdown,
        "runs": [r.to_dict() for _, r, _ in results],
    }
    out = RESULTS_DIR / f"mcp-quality-{stamp}.json"
    out.write_text(json.dumps(record, indent=2, default=str))
    print(f"\nWrote {out}")
    if args.set_baseline:
        BASELINE_PATH.write_text(json.dumps(record, indent=2, default=str))
        print(f"Set baseline: {BASELINE_PATH} (server {version})")
    return 0


def main() -> int:
    from evals._env import load_env

    load_env()
    p = argparse.ArgumentParser(description="MCP-quality arm comparison + diff.")
    p.add_argument("--n", type=int, default=1, help="reps per (arm, task)")
    p.add_argument("--arm", action="append", choices=ARMS, help="restrict arms; repeatable")
    p.add_argument("--concurrency", type=int, default=2)
    p.add_argument(
        "--baseline", help="results JSON to diff against (default: mcp-quality-baseline.json)"
    )
    p.add_argument("--set-baseline", action="store_true", help="record this run as the baseline")
    return asyncio.run(_main(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
