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
import os
from pathlib import Path

import httpx

from evals._common import is_manna_tool, judge_from_env, write_results
from evals.harness import SYSTEM_PROMPT, _max_steps
from evals.mcp_quality import _accuracy, _server_version
from evals.personas import PersonaConfig, _default_timeout_s, make_persona
from evals.score import load_tasks, score_task

TASKS_PATH = Path(__file__).with_name("mcp_quality_tasks.yaml")
_SCRATCH = os.environ.get("TMPDIR", "/tmp")  # neutral cwd for the persona subprocess


async def _serve(port: int, condition: str = "full"):
    # The ablated server is the same app booted inside evals.context.ablated_context.
    module = "evals._ablated_server" if condition == "ablated" else "manna"
    proc = await asyncio.create_subprocess_exec(
        "uv",
        "run",
        "python",
        "-m",
        module,
        env={**os.environ, "MANNA_PORT": str(port)},
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
    return any(is_manna_tool(c.tool) for c in run.trace)


def _same_model_persona(base_label: str) -> tuple[dict[str, str], str, str]:
    """Env pointing Claude Code at the SAME model as the custom loop (from EVAL_MODEL_*),
    for a like-for-like harness comparison. Returns (env, model, label)."""
    name = os.getenv("EVAL_MODEL_NAME") or os.getenv("ANTHROPIC_DEFAULT_OPUS_MODEL") or ""
    env = {
        "ANTHROPIC_API_KEY": "dummy",  # rides x-api-key; satisfies Claude Code login check
        "ANTHROPIC_MODEL": name,  # override any inherited default
        "ANTHROPIC_DEFAULT_OPUS_MODEL": name,
        "ANTHROPIC_DEFAULT_SONNET_MODEL": name,
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": name,
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "8192",
    }
    for src, dst in (
        ("EVAL_MODEL_BASE_URL", "ANTHROPIC_BASE_URL"),
        ("EVAL_MODEL_CUSTOM_HEADERS", "ANTHROPIC_CUSTOM_HEADERS"),
    ):
        if os.getenv(src):
            env[dst] = os.environ[src]
    short = name.split("/")[-1] or "model"
    return env, name, f"{base_label}@{short}"


async def _main(args: argparse.Namespace) -> int:
    tasks = load_tasks(TASKS_PATH)
    from evals.score import partition_by_archive, print_skipped

    # Same paused-archive skip as mcp_quality, so the two harnesses run the same task set.
    tasks, skipped = partition_by_archive(tasks)
    if skipped:
        print_skipped(skipped)
    if args.limit:
        tasks = tasks[: args.limit]
    judge = judge_from_env()
    base_name = args.persona  # registry key (e.g. "claude-code"); label may get an @model suffix
    p_env, p_model, p_label = {}, args.model, args.persona
    if args.same_model:
        p_env, p_model, p_label = _same_model_persona(args.persona)
    if not args.mcp:
        p_label += "-raw"  # without-MANNA approach: results file + arm say so
    if args.condition == "ablated":
        if not args.mcp:
            raise SystemExit("--condition ablated needs the MANNA server; drop --no-mcp")
        p_label += "-ablated"  # notes stripped: results file says so
    timeout_s = args.timeout if args.timeout is not None else _default_timeout_s()
    max_turns = args.max_turns if args.max_turns is not None else _max_steps()
    persona = make_persona(
        base_name,
        PersonaConfig(
            label=p_label,
            model=p_model,
            env=p_env,
            cwd=_SCRATCH,
            isolate=args.isolate,
            timeout_s=timeout_s,
            max_turns=max_turns,
            system_prompt=SYSTEM_PROMPT if args.system_prompt else None,
            mcp=args.mcp,
            condition=args.condition,
        ),
    )
    args.persona = p_label
    mcp_url = f"http://127.0.0.1:{args.port}/mcp/"

    print(
        f"persona: {args.persona}  |  judge: {judge.label if judge else 'none'}  |  "
        f"isolate: {'on' if args.isolate else 'off'}  |  timeout: {timeout_s:g}s  |  "
        f"max_turns: {max_turns}  |  prompt: {'parity' if args.system_prompt else 'none'}  |  "
        f"{len(tasks)} tasks  |  "
        + (
            f"condition: {args.condition}  |  booting MCP server on :{args.port} …"
            if args.mcp
            else "WITHOUT MANNA (no MCP server)"
        )
    )
    server = await _serve(args.port, args.condition) if args.mcp else None
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
        if server is not None:
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
        "mean_mcp_calls": mean([sum(is_manna_tool(c.tool) for c in r.trace) for r in runs]),
        "mean_turns": mean([r.steps for r in runs]),
        "mean_input_tokens": mean([r.input_tokens for r in ok]),
        "mean_output_tokens": mean([r.output_tokens for r in ok]),
        "total_cost_usd": round(sum(r.cost_usd or 0 for r in runs), 4),
        "mean_cost_usd": mean([r.cost_usd for r in runs if r.cost_usd is not None]),
        "mean_latency_s": mean([r.latency_s for r in ok]),
    }
    for k, v in summary.items():
        print(f"  {k:20s} {v}")

    model_used = next((r.persona_model for r in runs if r.persona_model), None)
    out = write_results(
        {
            "persona": args.persona,
            "model": model_used,
            "server_version": _server_version(),
            "isolated": args.isolate,
            "max_turns": max_turns,
            "timeout_s": timeout_s,
            "system_prompt": args.system_prompt,
            "mcp": args.mcp,
            "arm": "claude-code" if args.mcp else "claude-code-raw",
            "condition": args.condition,
            "summary": summary,
            "runs": [r.to_dict() for r in runs],
            "skipped": [t["id"] for t, _ in skipped],
        },
        prefix=f"persona-{args.persona}",
    )
    print(f"\nWrote {out}")
    return 0


def main() -> int:
    from evals._env import load_env

    load_env()
    p = argparse.ArgumentParser(description="Run the mcp_quality suite through an ACP persona.")
    from evals.personas import PERSONA_REGISTRY

    p.add_argument(
        "--persona",
        default="claude-code",
        choices=sorted(PERSONA_REGISTRY),
        help="harness driver to run the suite through",
    )
    p.add_argument("--model", default=None, help="persona model override (--model)")
    p.add_argument(
        "--same-model",
        action="store_true",
        help="drive the persona at the SAME model as the custom loop (EVAL_MODEL_*) for a "
        "like-for-like harness comparison",
    )
    p.add_argument(
        "--limit", type=int, default=None, help="run only the first N tasks (cost control)"
    )
    p.add_argument(
        "--no-isolate",
        dest="isolate",
        action="store_false",
        help="keep the developer's global hooks/plugins/settings active inside the persona "
        "(default: isolated)",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="wall-clock cap per task, in seconds (default: EVAL_PERSONA_TIMEOUT env, or 600)",
    )
    p.add_argument(
        "--max-turns",
        type=int,
        default=None,
        help="--max-turns cap passed to the persona (default: EVAL_MAX_STEPS env, or 20)",
    )
    p.add_argument(
        "--no-system-prompt",
        dest="system_prompt",
        action="store_false",
        help="do not append the custom loop's SYSTEM_PROMPT to the persona (default: appended, "
        "so the loop-vs-persona comparison differs only in the harness)",
    )
    p.add_argument(
        "--no-mcp",
        dest="mcp",
        action="store_false",
        help="the without-MANNA approach: run the persona with only its built-in tools and an "
        "empty strict MCP config (no server is booted); arm=claude-code-raw",
    )
    p.add_argument(
        "--condition",
        default="full",
        choices=["full", "ablated"],
        help="ablated = boot the server with its archive notes stripped (usage_notes, "
        "cheatsheet, error hints, describe_table entries) — the with-and-without comparison",
    )
    p.add_argument("--port", type=int, default=8127)
    p.add_argument("--concurrency", type=int, default=2)
    return asyncio.run(_main(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
