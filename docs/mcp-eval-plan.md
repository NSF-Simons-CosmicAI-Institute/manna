# Agentic evaluation plan for astro-archives-mcp

Status: **plan / design doc — review the task suite (§5) before we build the harness.**
Target model: the **dlai01 vLLM Qwen3.5** persona backend (the model we intend to ship on
gp13). Hosted Claude is used only as the *judge* and as an optional quality ceiling.

## 1. What we are actually measuring

We have already proven the **plumbing**: the persona (Claude Code ACP → Qwen3.5 on dlai01)
reaches `mcp:8000/mcp/`, enumerates all 12 `vo_*` tools, and a real end-to-end call resolved
M51 (`docs/examples/gp13/smoke-test.sh`, check 5). The repo's 221 offline tests also pin the
plumbing — but every one of them (including `tests/workflows/`) is **scripted**: a human wrote
the tool-call sequence "the LLM would make," with faked backends. **No LLM ever decides
anything in the current test suite.**

The open question is therefore *not* "do the tools work" but:

> **When Qwen3.5 is handed a real astronomer's task, does it use these tools to reach a
> correct, useful answer — and does the server's curated context make that happen?**

"Working" has four layers. We have (1); this plan builds (2)–(4):

| Layer | Question | Status |
|---|---|---|
| 1. Transport | Can the persona see and call the tools? | ✅ validated (smoke-test) |
| 2. Tool selection | Does the model map an intent to the *right tool + args*? | ⬜ this plan |
| 3. Task success | Does a multi-step task reach a *correct final answer*? | ⬜ this plan |
| 4. Contextual value | Do `usage_notes` / `schema_kb` actually prevent the known failure modes? | ⬜ this plan |

## 2. The core idea: this server's value IS its curated context

Layer 4 is the point of the project. A model could hit these archives with raw pyvo; what
this server adds is `known_archives.usage_notes`, `schema_kb`, and the
`error_class`/`retry_strategy` taxonomy. So the eval must specifically test whether that
context earns its keep. `known_archives.py` already encodes the exact traps to probe:

- **NRAO obscore data reads require `mode='async'`** — the `/sync` endpoint 5xxs.
- **NRAO obscore is at `tap_schema.obscore`, not `ivoa.obscore`.**
- **Data Lab does not translate ADQL geometry** → must use a bounding-box, not `CONTAINS`.
- **NRAO:** `LOWER`/`UPPER` fail; a spatial predicate is always required; `instrument_name ∈
  {EVLA, VLA, VLBA, GBT}`.
- **ALMA** rows are at spectral-window granularity (naive `COUNT` over-counts observations).

If Qwen3.5 **with** this server avoids these traps and Qwen3.5 **without** it falls in, the
server works. That delta is the headline metric.

This is complementary to — not a duplicate of — BFCL V4 / Tau2-bench (referenced in
`docs/local-model-backend.md`): those score a *model's* generic tool-calling; we score *this
server's* domain context with the model held fixed.

## 3. Non-goals

- **Not** re-testing transport, schema validity, or error-envelope shape — `tests/contracts/`
  and `tests/tools/` already own those; this eval assumes they pass.
- **Not** benchmarking Qwen3.5 as a general model (that's BFCL/Tau2, upstream of us).
- **Not** a load/concurrency test (separate concern, see gp13 runbook §5).

## 4. Harness architecture

Two harnesses. **Harness A is the workhorse** (all tiers run here). Harness B is a periodic
true-system gate.

### Harness A — scripted agent loop (primary)

A small Python driver (`evals/harness.py`) that runs a real agent loop:

```
task prompt ──► dlai01 vLLM (Qwen3.5, Anthropic Messages API)   [model decides]
                   │  emits tool_use blocks
                   ▼
             execute against Client(build_mcp())                 [real tools]
                   │  tool_result back into the conversation
                   ▼
             loop until final text answer  ──►  full trace recorded
```

- **Model calls** go to the real dlai01 vLLM over the Anthropic Messages API — the same
  endpoint the persona uses (`ANTHROPIC_BASE_URL` = datalab proxy, model
  `Qwen/Qwen3.5-122B-A10B-FP8`, per `deploy/frontend/.env.example`). We drive it directly,
  not through Claude Code ACP, so we get the full structured trace.
- **Tool execution** goes through the existing in-memory `Client(build_mcp())` pattern
  (`tests/conftest.py`) — but with **live network to the real archives** (eval measures real
  correctness, so no cassettes here; that's the deliberate difference from the unit tests).
- **Recorded per task:** ordered list of `(tool, args)` calls, each tool result envelope,
  final answer text, latency, token counts, and any error payloads seen.

Why direct-drive instead of the persona: reproducibility, full trace access, and it isolates
*server + model* from *ACP adapter* quirks. Harness B covers the ACP layer.

### Harness B — full end-to-end (periodic gate)

Generalize `docs/examples/gp13/smoke-test.sh` check 5: drive the actual Jupyter AI persona
(`claude -p '<task>'` inside the frontend container) for a handful of canary tasks, grep the
output for the golden answer. Catches persona/ACP/proxy regressions Harness A can't. Run it
before promoting a cut, not on every eval iteration.

## 5. Task dataset — REVIEW THIS

Tasks live in `evals/tasks.yaml`, versioned in-repo. Proposed schema per task:

```yaml
- id: resolve-m87
  tier: 2                      # 1=tool-selection, 2=task-success, 3=ablation-trap, 4=robustness
  prompt: "What are the ICRS coordinates of the galaxy M87?"
  expect_tools: [vo_target_resolve]      # tool(s) that MUST appear (order-free unless `sequence`)
  arg_checks:                            # constraints on the call's args
    vo_target_resolve: { name: {contains: "M87"} }
  ground_truth:                          # deterministic check on the final answer
    type: coords
    ra: 187.706
    dec: 12.391
    tol_deg: 0.01
  probes_trap: null                      # for tier-3 tasks, which usage_note this exercises
  rubric: null                           # for open-ended tasks, LLM-judge criteria
```

Below is the **proposed starter suite (~30 tasks)**. Ground truths marked ✔ are
deterministic (verified against the repo's own tests / smoke test); those marked ≈ are
plausibility/rubric-scored because live archive counts drift.

### Tier 1 — tool-selection accuracy (isolates the model, no chaining)

| id | prompt (abbrev) | expected tool | check |
|---|---|---|---|
| t1-resolve | "Coordinates of M87?" | `vo_target_resolve` | args.name~M87 |
| t1-list | "Which archives do you know about for radio data?" | `vo_archive_list` | args.waveband~radio |
| t1-schema | "Any quirks in NRAO's obscore table I should know?" | `vo_schema_describe` | args.archive=nrao, table~obscore |
| t1-registry | "Find me a TAP service for X-ray surveys." | `vo_registry_search` | servicetype=tap, waveband~x-ray |
| t1-cone | "List catalog sources within 0.05° of RA 187.7, Dec 12.4." | `vo_cone_search` | ra/dec/radius present |
| t1-sia | "Are there any images of this position in CADC?" | `vo_sia_search` | endpoint~cadc |
| t1-tap | "Run this ADQL against Data Lab: SELECT TOP 5 ..." | `vo_tap_query` | endpoint~datalab |

Score: right tool chosen (1/0) + args satisfy checks (1/0). Reports **tool-selection accuracy**.

### Tier 2 — multi-step task success (the real workflows)

Each maps to a chain the server is designed for. `sequence: true` means order matters.

| id | task | expected chain | ground truth |
|---|---|---|---|
| t2-resolve-cone | "Find catalog sources within 3 arcmin of M87." | `vo_target_resolve` → `vo_cone_search` | ✔ cone centered on 187.706/12.391 |
| t2-list-then-query | "How many VLASS observations does NRAO have near the Galactic center? Check the archive's quirks first." | `vo_archive_list` → `vo_tap_query(mode=async)` | ≈ nonzero rows, async used |
| t2-async-lifecycle | "Query NRAO obscore for EVLA observations (this may be slow)." | `vo_tap_query(async)` → `vo_tap_status`(poll) → `vo_tap_results` | ✔ COMPLETED then results envelope |
| t2-unknown-archive | "I want proper motions from Gaia DR3 — find the right service and query it." | `vo_registry_search`→`vo_registry_describe`→`vo_tap_query` | ≈ gaia tap_url discovered |
| t2-sia-fetch | "Get me a FITS image covering M51 from CADC." | `vo_target_resolve`→`vo_sia_search` | ✔ access_url returned (client fetches it; CADC via DataLink) |
| t2-schema-bound-query | "Query NRAO obscore for GBT observations." | `vo_schema_describe`→`vo_tap_query(async)` | ✔ uses instrument_name='GBT' from enum |
| t2-datalab-geometry | "Count Data Lab NSC DR2 objects in a 0.1° box around M87." | `vo_target_resolve`→`vo_tap_query` | ✔ bounding-box (ra/dec BETWEEN), not CONTAINS |

Score per task on a rubric: **reached correct final answer** (programmatic where ground_truth
is deterministic; else LLM-judge), **# tool calls** (efficiency), **error-recovery** (did it
recover if a call failed). Reports **task success rate** + **mean tool-calls/task**.

### Tier 3 — contextual-value ablation (the differentiator)

Run each trap task **twice**: (a) with the server as-is, (b) with `usage_notes` +
`schema_kb` stripped (a `build_mcp(context=False)` flag or a monkeypatched empty KB). Measure
**trap-avoidance rate** in each condition; the delta is the server's ROI.

| id | trap probed | "avoided" means |
|---|---|---|
| t3-nrao-async | NRAO data read needs `mode='async'` | model used async (didn't hammer /sync into 5xx) |
| t3-obscore-location | obscore at `tap_schema.obscore` not `ivoa.obscore` | queried the correct table name |
| t3-datalab-geometry | Data Lab doesn't translate ADQL geometry | used bounding-box, not `CONTAINS`/`CIRCLE` |
| t3-nrao-lowerupper | `LOWER`/`UPPER` fail on NRAO | avoided them / recovered after the error |
| t3-nrao-spatial | NRAO requires a spatial predicate | included one |
| t3-alma-granularity | ALMA rows are per spectral-window | didn't report window count as observation count |

Hypothesis to confirm: **with-context avoidance ≫ without-context avoidance.** If the delta is
small, either the model already knows the archives (unlikely for NRAO quirks) or the notes
aren't landing — both are actionable findings.

### Tier 4 — robustness / safety

| id | input | expected behavior |
|---|---|---|
| t4-bad-adql | syntactically broken ADQL | surfaces `error_class`, model reads `retry_strategy`, fixes & retries |
| t4-unknown-archive | "query the FooBar archive" | falls back to `vo_registry_search` (per tool guidance) |
| t4-job-not-ready | fetch async results before COMPLETED | model polls `vo_tap_status` instead of erroring out |
| t4-no-leak | force an internal error | **assert** no token/traceback text in any payload the model saw (`redact_message` invariant) |

## 6. Scoring

- **Programmatic** for deterministic ground truth: coordinate tolerance, exact table/tool
  names, envelope keys (`mode=='async'`, `result_url`/`fetch_recipe` present), trap booleans parsed from
  the recorded tool args.
- **LLM-as-judge** (hosted Claude, *not* Qwen3.5 grading itself) for open-ended answer
  quality, using each task's `rubric`. Judge sees the prompt, the final answer, and the tool
  trace; returns pass/fail + a 1–5 quality score + one-line justification.
- Every score ties back to the recorded trace so failures are debuggable.

## 7. Metrics & baselines

Tracked per run, written to `evals/results/<timestamp>.json`:

- Tool-selection accuracy (Tier 1)
- Task success rate (Tier 2)
- **Trap-avoidance rate, with-context vs. without-context (Tier 3)** ← headline
- Error-recovery rate (Tier 4)
- Mean tool-calls per task (efficiency); latency; token cost per task

**Baselines:**
1. Qwen3.5 **with** context vs. **without** (Tier 3 ablation) — measures the *server*.
2. (Optional) Qwen3.5 vs. hosted Claude on Tiers 1–2 — measures how much is *model* vs.
   *server*, and sets a quality ceiling.

## 8. Proposed repo layout

```
evals/
├── tasks.yaml          # the versioned task suite (§5) — review target
├── harness.py          # agent loop: dlai01 vLLM ↔ Client(build_mcp()), records traces
├── score.py            # programmatic + LLM-judge scoring
├── run.py              # CLI: `uv run python -m evals.run --tier 2 --model qwen`
├── results/            # timestamped JSON runs (git-ignored or committed as a record)
└── README.md           # how to run, how to add a task
```

Runs are **live-network by design** (real archive correctness), so they are not hermetic like
the pytest suite — they belong in `evals/`, not `tests/`, and are invoked on demand, not in
the default `pytest` run. A trimmed Tier-1 subset could later gate CI once we trust stability.

## 9. Sequencing (after this doc is approved)

1. Vet & freeze `evals/tasks.yaml` (§5). ← **you are here**
2. Build Harness A + scoring; run Tiers 1–2 against dlai01 Qwen3.5 → first real success number.
3. Add Tier 3 ablation (`build_mcp` context toggle) → the headline with/without delta.
4. Add Tier 4 + wire a Tier-1 subset into Harness B (persona canaries).

## 10. Open decisions

- **Ablation mechanism:** add a `build_mcp(include_context=False)` flag vs. monkeypatch the
  KB modules in the harness. A flag is cleaner and reusable; slight production-code touch.
- **Live-archive flakiness:** archives go down / change row counts. Mitigate with retries +
  marking count-based ground truths as ≈ (plausibility), reserving ✔ for stable facts
  (coordinates, table names, enum values).
- **Judge cost/independence:** hosted Claude as judge adds an API dependency to eval runs;
  acceptable since judging is offline and cheap relative to the agent loop.
- **How many tasks:** ~30 is enough for signal without being slow against a single-GPU-hosted
  model; expand per trap as we find new failure modes.
