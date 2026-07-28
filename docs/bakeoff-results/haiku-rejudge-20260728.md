# Haiku re-judge verdicts (2026-07-28)

Judge: `claude-haiku-4-5-20251001` via `evals/rejudge.py` (re-scores saved traces;
no model-under-test inference). Q scores are 1-5; PASS threshold per rubric.

## nemotron3-super (run-20260728T112653) — rubric 0.500 (4 judged)
- PASS q=4 t2-resolve-cone — resolved M87, 0.05 deg cone, plausible sources; slightly non-standard call format
- FAIL q=1 t2-list-then-query — no archive-notes consult, no successful TAP query, no final answer
- PASS q=5 t2-unknown-archive — registry-discovered Gaia TAP, schema inspection, valid PM query
- FAIL q=1 t2-sia-fetch — SIA search fine but no final answer / no fetchable FITS URL

## gpt-oss-120b (run-20260728T114137) — rubric 0.750 (4 judged)
- PASS q=5 t2-resolve-cone — M87 resolved, 0.05 deg cone, 60 well-formatted Gaia DR2 sources
- PASS q=5 t2-list-then-query — consulted quirks, async TAP w/ CONTAINS predicate, definitive count
- PASS q=5 t2-unknown-archive — Gaia DR3 endpoint discovered, schema inspected, valid query
- FAIL q=2 t2-sia-fetch — found CADC image but reported DataLink doc URL instead of following indirection to the FITS access_url

## gemma4-31b (run-20260728T115659) — rubric 0.500 (4 judged)
- PASS q=5 t2-resolve-cone — exact resolve, correct radius, 60 plausible Gaia DR2 sources
- FAIL q=2 t2-list-then-query — proper async submit but 20 status checks, no final count
- PASS q=5 t2-unknown-archive — registry discovery + describe + proper TAP query
- FAIL q=2 t2-sia-fetch — DataLink URL reported instead of the FITS file URL

## qwen3.5 baseline (run-20260720T152001, tiers 1-4) — rubric 0.400 (10 judged)
Same-4-task tier-2 subset: 0.500 (resolve-cone PASS q=5, list-then-query FAIL q=1,
unknown-archive PASS q=5, sia-fetch FAIL q=1). Others: t3-alma-granularity FAIL q=1 (x2,
no final answer despite correct COUNT(DISTINCT) queries), t4-bad-adql PASS q=5,
t4-unknown-archive PASS q=4, t4-job-not-ready FAIL q=2, t4-no-leak FAIL q=2.

## Common failure mode across all four models
t2-sia-fetch's DataLink indirection (reporting the DataLink document URL instead of
following it to the FITS access_url) failed for every model — likely a task/tooling
affordance issue worth a server-side look (surface the final URL more directly?).
