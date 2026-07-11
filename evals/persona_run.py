"""Run the mcp_quality suite through a REAL agent harness (an ACP persona) and score it.

Pillar-2 harness axis. Boots a local MCP server, drives each task through the persona
(Claude Code today), and scores the resulting TaskRun with the same judge/ground-truth as
the custom loop — so you can compare "custom loop vs Claude Code, same tasks". Adds a
persona-specific metric, tool_use_rate: how often the harness actually called an MCP tool
vs. answered from the model's memory.

    # boots its own MCP server; persona uses whatever `claude` is authed with
    uv run python -m evals.persona_run --limit 3          # validate on a few tasks
    uv run python -m evals.persona_run                    # full suite (uses your Claude quota)

Cost note: each task is a real `claude -p` run on your Claude account — start with --limit.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

import httpx

from evals.mcp_quality import _accuracy, _judge_from_env
from evals.personas import ClaudeCodePersona, PersonaConfig
from evals.score import load_tasks, score_task

TASKS_PATH = Path(__file__).with_name("mcp_quality_tasks.yaml")
RESULTS_DIR = Path(__file__).with_name("results")
_SCRATCH = os.environ.get("TMPDIR", "/tmp")  # neutral cwd for the persona subprocess


async def _serve(port: int):
    proc = await asyncio.create_subprocess_exec(
        "uv",
        "run",
        "python",
        "-m",
        "astro_archives_mcp",
        env={**os.environ, "STABLE_PORT": str(port)},
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    async with httpx.AsyncClient() as c:
        for _ in range(60):
            try:
                if (await c.get(f"http://127.0.0.1:{port}/health", timeout=2)).status_code == 200:
                    return proc
            except Exception:
                pass
            await asyncio.sleep(1)
    proc.terminate()
    raise RuntimeError("MCP server did not come up")


def _used_mcp(run) -> bool:
    return any(c.tool.startswith("vo_") for c in run.trace)


async def _main(args: argparse.Namespace) -> int:
    tasks = load_tasks(TASKS_PATH)
    if args.limit:
        tasks = tasks[: args.limit]
    judge = _judge_from_env()
    persona = ClaudeCodePersona(PersonaConfig(label=args.persona, model=args.model, cwd=_SCRATCH))
    mcp_url = f"http://127.0.0.1:{args.port}/mcp/"

    print(
        f"persona: {args.persona}  |  judge: {judge.label if judge else 'none'}  |  "
        f"{len(tasks)} tasks  |  booting MCP server on :{args.port} …"
    )
    server = await _serve(args.port)
    runs, accs = [], []
    try:
        sem = asyncio.Semaphore(args.concurrency)

        async def one(task):
            async with sem:
                run = await persona.run(task, mcp_url)
            acc = _accuracy(await score_task(task, run, judge))
            tag = {True: "PASS", False: "FAIL", None: "····"}[acc]
            print(
                f"  [{tag}] {task['id']:26s} calls={run.num_tool_calls} "
                f"mcp={'y' if _used_mcp(run) else 'n'} turns={run.steps}"
            )
            return run, acc

        results = await asyncio.gather(*(one(t) for t in tasks))
        runs = [r for r, _ in results]
        accs = [a for _, a in results]
    finally:
        server.terminate()
        await server.wait()

    ok = [r for r in runs if not r.error]
    scored = [a for a in accs if a is not None]
    print("\n" + "=" * 60)
    print(f"PERSONA: {args.persona}")
    print("=" * 60)

    def mean(xs):
        return round(sum(xs) / len(xs), 2) if xs else 0

    summary = {
        "accuracy_rate": round(sum(scored) / len(scored), 3) if scored else None,
        "completion_rate": round(
            sum(bool(r.final_answer.strip()) and not r.error for r in runs) / len(runs), 3
        ),
        "tool_use_rate": round(sum(_used_mcp(r) for r in runs) / len(runs), 3),
        "mean_mcp_calls": mean([sum(c.tool.startswith("vo_") for c in r.trace) for r in runs]),
        "mean_turns": mean([r.steps for r in runs]),
        "mean_output_tokens": mean([r.output_tokens for r in ok]),
        "mean_latency_s": mean([r.latency_s for r in ok]),
    }
    for k, v in summary.items():
        print(f"  {k:20s} {v}")

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    out = RESULTS_DIR / f"persona-{args.persona}-{stamp}.json"
    out.write_text(
        json.dumps(
            {"persona": args.persona, "summary": summary, "runs": [r.to_dict() for r in runs]},
            indent=2,
            default=str,
        )
    )
    print(f"\nWrote {out}")
    return 0


def main() -> int:
    from evals._env import load_env

    load_env()
    p = argparse.ArgumentParser(description="Run the mcp_quality suite through an ACP persona.")
    p.add_argument("--persona", default="claude-code")
    p.add_argument("--model", default=None, help="persona model override (--model)")
    p.add_argument(
        "--limit", type=int, default=None, help="run only the first N tasks (cost control)"
    )
    p.add_argument("--port", type=int, default=8127)
    p.add_argument("--concurrency", type=int, default=2)
    return asyncio.run(_main(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
