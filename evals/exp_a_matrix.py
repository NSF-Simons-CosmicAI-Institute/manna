"""Experiment (a), controlled matrix: does description-injection deliver the
curated archive quirks when the model can't (or won't) consult the discovery tools?

Since issue #57 this measures a SHIPPED feature, not a hypothetical: the server
injects the cheatsheet of up-front notes into run_adql_query's description by default
(archives/_pitfalls.py, derived from notes tagged with a triggerless `Pitfall`). So the
`inject` axis inverted — cell C now STRIPS the blob rather than cell D adding it.
The cells and the decisive comparison are otherwise unchanged, so the numbers
below remain the reference.

Cells (all full server context; the axis is what the MODEL can reach):
  A = discovery ON,  inject ON    (real-world reference — production default)
  C = discovery OFF, inject OFF   (blind — cheatsheet stripped, model priors only)
  D = discovery OFF, inject ON    (quirks reach the model only via run_adql_query desc)

Decisive comparison: C -> D. Scored programmatically (arg-checks = pitfall avoided);
run against the live model, so pitfall tasks that submit an async query still score from
the SUBMITTED adql — set EVAL_MAX_STEPS/EVAL_ASYNC_POLL_SLEEP low to run fast:

    EVAL_MAX_STEPS=8 EVAL_ASYNC_POLL_SLEEP=1 \\
      uv run python -m evals.exp_a_matrix        # (with model creds sourced)

Reference result, pre-#57 (Qwen3.5, N=3) (historical, Qwen3.5-era): A=15/15, C=0/15, D=12/15. The 3 misses were
all t3-nrao-lowerupper — an ERROR-HINT pitfall deliberately NOT in the cheatsheet. #57 gave that
pitfall the OTHER channel (the error `hint`), which this matrix does not isolate: the hint
fires on a live rejection in every cell. Judge it from the tier-3 run instead.
"""

import asyncio

from evals.harness import ModelConfig, _max_steps, run_task
from evals.score import load_tasks, partition_by_archive, print_skipped, score_programmatic

PITFALL_TASKS = [
    "t3-datalab-geometry",  # cleanest: datalab endpoint is in tool examples
    "t3-obscore-location",
    "t3-nrao-async",
    "t3-nrao-lowerupper",
    "t3-nrao-spatial",
]
CELLS = {
    # A is production as shipped: discovery available AND the up-front notes injected.
    # Cell labels are kept verbatim — they appear in saved output.
    "A disc/INJ": dict(no_discovery=False, inject_notes=True),
    "C nodisc/noinj": dict(no_discovery=True, inject_notes=False),
    "D nodisc/INJ": dict(no_discovery=True, inject_notes=True),
}
N = 3


def runnable_pitfall_tasks() -> list[dict]:
    """PITFALL_TASKS, minus any that require an archive not in the active set.

    nrao ships paused, so most of PITFALL_TASKS is skipped by default —
    running them against a default server would load the endpoint we agreed
    to leave alone. Activate nrao via MANNA_ARCHIVES to run them.
    """
    tasks = [t for t in load_tasks() if t["id"] in PITFALL_TASKS]
    tasks, skipped = partition_by_archive(tasks)
    if skipped:
        print_skipped(skipped)
    return tasks


async def main():
    cfg = ModelConfig.from_env()
    runnable = runnable_pitfall_tasks()
    if not runnable:
        print("No pitfall tasks left to run (all require a paused archive) — nothing to do.")
        return 1
    tasks = {t["id"]: t for t in runnable}
    pitfall_ids = [tid for tid in PITFALL_TASKS if tid in tasks]
    print(f"model={cfg.label}  MAX_STEPS={_max_steps()}  N={N} per cell/pitfall\n")

    sem = asyncio.Semaphore(2)

    async def one(cell, flags, tid):
        async with sem:
            try:
                run = await run_task(tasks[tid], cfg, "full", **flags)
            except Exception:  # never let one flaky call kill the matrix
                return cell, tid, None
        return cell, tid, score_programmatic(tasks[tid], run).passed

    jobs = [
        one(cell, flags, tid)
        for cell, flags in CELLS.items()
        for tid in pitfall_ids
        for _ in range(N)
    ]
    results = await asyncio.gather(*jobs, return_exceptions=True)

    tally = {c: {t: 0 for t in pitfall_ids} for c in CELLS}
    for r in results:
        if isinstance(r, BaseException) or r is None:
            continue
        cell, tid, passed = r
        if passed is not None:
            tally[cell][tid] += int(passed)

    print(f"{'pitfall':22s}" + "".join(f"{c:>16s}" for c in CELLS))
    for tid in pitfall_ids:
        print(f"{tid:22s}" + "".join(f"{f'{tally[c][tid]}/{N}':>16s}" for c in CELLS))
    print("-" * (22 + 16 * len(CELLS)))
    denom = len(pitfall_ids) * N
    totals = {c: sum(tally[c].values()) for c in CELLS}
    print(
        f"{'AVOIDANCE (all pitfalls)':22s}"
        + "".join(f"{f'{totals[c]}/{denom}':>16s}" for c in CELLS)
    )
    print(f"{'rate':22s}" + "".join(f"{totals[c] / denom:>16.2f}" for c in CELLS))


if __name__ == "__main__":
    from evals._env import load_env, refresh_active_set

    load_env()
    # The active set is cached at import (tools/tap.py builds its endpoint
    # examples at import time), before .env is loaded. Re-read it so a
    # MANNA_ARCHIVES line in evals/.env can re-enable a paused archive.
    refresh_active_set()
    raise SystemExit(asyncio.run(main()))
