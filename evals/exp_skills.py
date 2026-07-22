"""Experiment: do the repo's workflow skills (skills/vo-*) improve multi-step
archive workflows?

A/B over the PERSONA path only — real `claude -p` natively loads Agent Skills from
<cwd>/.claude/skills/, so the lever is simply what the cwd contains (the same
mechanism exp_verbosity uses for its concision CLAUDE.md):

  S0  baseline persona, empty cwd
  S1  identical persona, cwd seeded with skills/vo-* from this repo

Prompts are the workflow-heavy subset of mcp_quality_tasks.yaml (incl. the
async-handoff task). Rubric accuracy needs EVAL_JUDGE_*; without a judge those
tasks report completion + efficiency only.

Run (with evals/.env present; uses the dlai01 vLLM endpoint like exp_verbosity):
    uv run python -m evals.exp_skills --dry-run     # show the plan, no calls
    uv run python -m evals.exp_skills --reps 3
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Any

from evals._common import judge_from_env, mean, write_results
from evals.harness import TaskRun
from evals.personas import PersonaConfig, make_persona
from evals.score import TaskScore, load_tasks, score_task

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
TASKS_PATH = Path(__file__).with_name("mcp_quality_tasks.yaml")

# Workflow-heavy subset: multi-step tasks where orchestration guidance can matter.
TASK_IDS = [
    "mq-workflow-gaia-pm",
    "mq-workflow-datalab-count",
    "mq-workflow-nrao-count",
    "mq-download-m51-image",
    "mq-async-handoff-nrao",
]

ARMS = ["S0", "S1"]


def load_prompts() -> list[dict[str, Any]]:
    by_id = {t["id"]: t for t in load_tasks(TASKS_PATH)}
    missing = [i for i in TASK_IDS if i not in by_id]
    if missing:
        raise SystemExit(f"tasks missing from {TASKS_PATH.name}: {missing}")
    return [by_id[i] for i in TASK_IDS]


def write_cwd(with_skills: bool) -> str:
    """Fresh temp dir for the persona cwd; S1 gets skills/vo-* under .claude/skills/."""
    d = tempfile.mkdtemp(prefix=f"cosmic-skills-{'on' if with_skills else 'off'}-")
    if with_skills:
        dest = Path(d) / ".claude" / "skills"
        dest.mkdir(parents=True)
        for src in sorted(SKILLS_DIR.glob("vo-*")):
            shutil.copytree(src, dest / src.name)
    return d


def _accuracy(score: TaskScore) -> bool | None:
    """Ground-truth verdict if present, else judged rubric, else None (unscored)."""
    if "ground_truth" in score.checks:
        return score.checks["ground_truth"]
    return score.checks.get("rubric")


def metric_row(
    arm: str, task: dict[str, Any], run: TaskRun, acc: bool | None, rep: int
) -> dict[str, Any]:
    return {
        "arm": arm,
        "task_id": task["id"],
        "rep": rep,
        "accuracy": acc,
        "completed": bool(run.final_answer.strip()) and not run.error,
        "num_tool_calls": run.num_tool_calls,
        "output_tokens": run.output_tokens,
        "latency_s": round(run.latency_s, 2),
        "error": run.error,
        "final_answer": run.final_answer,
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    by_arm: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_arm.setdefault(r["arm"], []).append(r)
    for arm, rs in by_arm.items():
        scored = [r["accuracy"] for r in rs if r["accuracy"] is not None]
        out[arm] = {
            "n": len(rs),
            "accuracy_rate": round(mean([1.0 if a else 0.0 for a in scored]), 2)
            if scored
            else None,
            "accuracy_scored_n": len(scored),
            "completion_rate": round(mean([1.0 if r["completed"] else 0.0 for r in rs]), 2),
            "mean_tool_calls": round(mean([r["num_tool_calls"] for r in rs]), 1),
            "mean_output_tokens": round(mean([r["output_tokens"] for r in rs]), 1),
            "mean_latency_s": round(mean([r["latency_s"] for r in rs]), 1),
            "error_rate": round(mean([1.0 if r["error"] else 0.0 for r in rs]), 2),
        }
    return out


_COLS = [
    ("accuracy_rate", "acc"),
    ("completion_rate", "compl"),
    ("mean_tool_calls", "calls"),
    ("mean_output_tokens", "out-tok"),
    ("mean_latency_s", "lat(s)"),
    ("error_rate", "err"),
]


def format_table(summary: dict[str, dict[str, Any]]) -> str:
    hdr = f"{'arm':6s}{'n':>4s}" + "".join(f"{label:>10s}" for _, label in _COLS)
    lines = [hdr, "-" * len(hdr)]
    for arm in ARMS:
        if arm not in summary:
            continue
        s = summary[arm]
        lines.append(f"{arm:6s}{s['n']:>4d}" + "".join(f"{str(s[k]):>10s}" for k, _ in _COLS))
    return "\n".join(lines)


async def _run_arm(arm: str, task, mcp_url, base_env, model_name) -> TaskRun:
    persona = make_persona(
        "claude-code",
        PersonaConfig(label=arm, model=model_name, env=base_env, cwd=write_cwd(arm == "S1")),
    )
    return await persona.run(task, mcp_url)


async def _main(args: argparse.Namespace) -> int:
    prompts = load_prompts()
    if args.dry_run:
        print(f"PLAN: {len(ARMS)} arms × {len(prompts)} prompts × {args.reps} reps")
        for arm in ARMS:
            for p in prompts:
                for rep in range(args.reps):
                    print(f"  {arm}(skills={'on' if arm == 'S1' else 'off'}) {p['id']} rep={rep}")
        return 0

    judge = judge_from_env()
    from evals.persona_run import _same_model_persona, _serve

    base_env, model_name, _ = _same_model_persona("claude-code")
    print(
        f"model={model_name}  judge={judge.label if judge else 'none'}  "
        f"arms={ARMS}  reps={args.reps}"
    )
    print(f"booting MCP server on :{args.port} …")
    server = await _serve(args.port)
    mcp_url = f"http://127.0.0.1:{args.port}/mcp/"
    sem = asyncio.Semaphore(args.concurrency)

    async def one(arm: str, task, rep: int) -> dict[str, Any]:
        async with sem:
            try:
                run = await _run_arm(arm, task, mcp_url, base_env, model_name)
            except Exception as exc:  # never let one flaky call kill the matrix
                run = TaskRun(task["id"], task["tier"], "full", arm)
                run.error = f"{type(exc).__name__}: {exc}"
        acc = _accuracy(await score_task(task, run, judge))
        row = metric_row(arm, task, run, acc, rep)
        tag = {True: "PASS", False: "FAIL", None: "····"}[acc]
        print(
            f"  [{tag}] {arm} {task['id']:26s} rep{rep} "
            f"calls={row['num_tool_calls']} tok={row['output_tokens']} err={bool(row['error'])}"
        )
        return row

    try:
        jobs = [one(a, p, r) for a in ARMS for p in prompts for r in range(args.reps)]
        rows = await asyncio.gather(*jobs)
    finally:
        server.terminate()
        await server.wait()

    summary = aggregate(rows)
    print("\n" + format_table(summary))
    out = write_results(
        {"summary": summary, "rows": rows, "task_ids": TASK_IDS}, prefix="skills-ab"
    )
    print(f"\nWrote {out}")
    return 0


def main() -> int:
    from evals._env import load_env

    load_env()
    p = argparse.ArgumentParser(description="Workflow-skills A/B (persona path).")
    p.add_argument("--reps", type=int, default=3, help="repetitions per (arm, prompt)")
    p.add_argument("--concurrency", type=int, default=2, help="keep low; single shared GPU")
    p.add_argument("--port", type=int, default=8131, help="port for the experiment's MCP server")
    p.add_argument("--dry-run", action="store_true", help="print the plan; make no model calls")
    return asyncio.run(_main(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
