"""Experiment (a), controlled matrix: does description-injection deliver the
curated archive quirks when the model can't (or won't) consult the discovery tools?

Cells (all full server context; the axis is what the MODEL can reach):
  A = discovery ON,  inject OFF   (real-world reference)
  C = discovery OFF, inject OFF   (blind — model priors only)
  D = discovery OFF, inject ON    (quirks reach the model only via vo_tap_query desc)

Decisive comparison: C -> D. Scored programmatically (arg-checks = trap avoided);
run against the live model, so trap tasks that submit an async query still score from
the SUBMITTED adql — set EVAL_MAX_STEPS/EVAL_ASYNC_POLL_SLEEP low to run fast:

    EVAL_MAX_STEPS=8 EVAL_ASYNC_POLL_SLEEP=1 \\
      uv run python -m evals.exp_a_matrix        # (with model creds sourced)

First live result (Qwen3.5, N=3): A=15/15, C=0/15, D=12/15. The 3 misses are all
t3-nrao-lowerupper — a LOUD trap deliberately NOT in the cheatsheet (it belongs in the
error hint). So injection recovers exactly the traps it covers.
"""

import asyncio

from evals.harness import MAX_STEPS, ModelConfig, run_task
from evals.score import load_tasks, score_programmatic

TRAPS = [
    "t3-datalab-geometry",  # cleanest: datalab endpoint is in tool examples
    "t3-obscore-location",
    "t3-nrao-async",
    "t3-nrao-lowerupper",
    "t3-nrao-spatial",
]
CELLS = {
    "A disc/noinj": dict(no_discovery=False, inject_notes=False),
    "C nodisc/noinj": dict(no_discovery=True, inject_notes=False),
    "D nodisc/INJ": dict(no_discovery=True, inject_notes=True),
}
N = 3


async def main():
    cfg = ModelConfig.from_env()
    tasks = {t["id"]: t for t in load_tasks() if t["id"] in TRAPS}
    print(f"model={cfg.label}  MAX_STEPS={MAX_STEPS}  N={N} per cell/trap\n")

    sem = asyncio.Semaphore(2)

    async def one(cell, flags, tid):
        async with sem:
            try:
                run = await run_task(tasks[tid], cfg, "full", **flags)
            except Exception:  # never let one flaky call kill the matrix
                return cell, tid, None
        return cell, tid, score_programmatic(tasks[tid], run).passed

    jobs = [
        one(cell, flags, tid) for cell, flags in CELLS.items() for tid in TRAPS for _ in range(N)
    ]
    results = await asyncio.gather(*jobs, return_exceptions=True)

    tally = {c: {t: 0 for t in TRAPS} for c in CELLS}
    for r in results:
        if isinstance(r, BaseException) or r is None:
            continue
        cell, tid, passed = r
        if passed is not None:
            tally[cell][tid] += int(passed)

    print(f"{'trap':22s}" + "".join(f"{c:>16s}" for c in CELLS))
    for tid in TRAPS:
        print(f"{tid:22s}" + "".join(f"{f'{tally[c][tid]}/{N}':>16s}" for c in CELLS))
    print("-" * (22 + 16 * len(CELLS)))
    denom = len(TRAPS) * N
    totals = {c: sum(tally[c].values()) for c in CELLS}
    print(
        f"{'AVOIDANCE (all traps)':22s}" + "".join(f"{f'{totals[c]}/{denom}':>16s}" for c in CELLS)
    )
    print(f"{'rate':22s}" + "".join(f"{totals[c] / denom:>16.2f}" for c in CELLS))


if __name__ == "__main__":
    from evals._env import load_env

    load_env()
    asyncio.run(main())
