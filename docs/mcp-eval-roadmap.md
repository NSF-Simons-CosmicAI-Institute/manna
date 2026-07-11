# Evaluation & QA program for astro-archives-mcp

Status: **all three pillars shipped** (2026-07-11, branch `dpg/mcp-eval-harness`). This doc
is the design reference + map of what each piece does; read it at the start of any session
that works on evaluation. Companion docs: `docs/mcp-eval-plan.md` (the 4-tier task design +
first-run findings), memory `eval-harness-findings` (results vs. live Qwen3.5).

## What's built (quick map)

| Pillar | Entry point | What it does |
|---|---|---|
| 1 — MCP quality | `evals/mcp_quality.py` | 3 arms (mcp / raw_tap / raw_web) × task suite, per-tool/per-archive breakdown, version-over-version diffing + baseline |
| 2 — model axis | `evals/model_backends.py` | neutral backend + Anthropic (Messages) **and** OpenAI (Chat Completions) adapters — one code path drives Qwen, OpenAI models, any OpenAI-style open-weights |
| 2 — harness axis | `evals/personas.py`, `evals/persona_run.py` | Claude Code persona driver (registry + `Persona` protocol), boots the server, `--same-model` for like-for-like harness comparison |
| 2 — scorecard | `evals/scorecard.py` | weighted per-`(model×harness)` grade across WORKFLOW + MCP-COMPATIBILITY axes, with a task-set comparability guard |
| 2 — judge | `evals/score.py` | rubric judge routes through the backend layer → Anthropic **or** OpenAI judge |
| 3 — caveats | `evals/caveats.py` | model-free live probe per KB caveat → STILL-TRUE / STALE / UNREACHABLE, control-gated |

Shared: `evals/harness.py` (agent loop + neutral conversation), `evals/score.py` (checks +
judge), `evals/_env.py` (gitignored `evals/.env`), `evals/providers.py` (tool-provider arms),
`evals/rejudge.py` (re-judge saved answers).

## The three things we want to test

1. **MCP quality** — is the server actually doing its job: making data discovery +
   download easier, in fewer agent iterations, fewer tokens, and more accurately? Used to
   *refine the server* (toolset, `usage_notes`, `schema_kb`).
2. **Model / harness matrix** — how well do different **models** (Anthropic API,
   open-weights) and different **harnesses** (Claude Code persona, Gemini CLI, Goose, … —
   not just one custom loop) work with the server, both (a) at the tool-calling
   compatibility level and (b) at answering end-to-end astronomical workflow questions.
   Needs a grading rubric / scorecard.
3. **Archive caveat regression** — for each documented archive quirk/caveat, verify over
   time that it *still holds* on the live archive, and raise a flag if it doesn't (the
   archive fixed it → the note is now stale).

## Architecture (the seam all three pillars hang off)

**Driver (model-adapter × harness) → Trace → Rubric/Scorer**, plus a **separate, model-free
caveat suite**. `evals/harness.py` drives a model through a neutral conversation against an
in-memory `Client(build_mcp())` with **live archives**, recording the full trace (tool calls,
args, results, final answer) + tokens / iterations / latency. `make_backend` (model axis) and
`make_persona` (harness axis) are the two Driver interchange points; `score.py` +
`scorecard.py` are the Rubric/Scorer. Pillar-1 measurement levers (context ablation,
`--no-discovery`, `--inject-notes`) live in the harness — **don't trim them**.

## Pillar 1 — MCP quality (refine the server) — **SHIPPED**

`evals/mcp_quality.py`. Both levers built: (a) the **3-arm A/B baseline** (`mcp` vs
`raw_tap` vs `raw_web`, `evals/providers.py`) for the headline "is the server worth it" lift,
and (b) **version-over-version diffing** (`--set-baseline` → gitignored
`results/mcp-quality-baseline.json`) with a task-set-change guard, plus per-tool / per-archive
breakdown reporting.

Result (18-task suite, Qwen3.5, Haiku judge): **mcp acc 0.94, 0 tool-errors** vs raw_tap
0.33 / raw_web 0.39 — MCP lift is large and holds on the broader suite. Two refinement leads
surfaced and filed: **#41** (ESO has no `usage_notes` → agents flail) and **#42** (CADC
download stops at the DataLink VOTable, never resolves the FITS). Full findings in memory
`eval-harness-findings`.

## Pillar 2 — model / harness matrix + rubric — **SHIPPED**

- **Model-adapter layer** (`evals/model_backends.py`): neutral `ModelBackend` +
  `AnthropicBackend` (Messages API) + `OpenAIBackend` (Chat Completions); `make_backend(cfg)`
  picks by `EVAL_MODEL_BACKEND`. Validated: the *same* Qwen3.5 via both backends gives
  identical results — so OpenAI models and any OpenAI-style open-weights are testable.
- **Harness driver** (`evals/personas.py`, `evals/persona_run.py`): Claude Code persona
  (`claude -p --output-format stream-json`) with the MCP server registered inline, transcript
  parsed into the same `TaskRun`. Generalized into a `Persona` protocol + `PERSONA_REGISTRY`
  so adding a driver is one registry entry. **Only `claude-code` is registered** — it is the
  one agent CLI installed here (gemini/goose/codex/etc. are not installed, so shipping
  unvalidatable drivers would be dead code; add them to the registry when installed).
  `--same-model` drives the persona at the same Qwen as the custom loop for a like-for-like
  harness comparison.
- **Judge** (`evals/score.py`): routes through the backend layer → Anthropic **or** OpenAI
  judge (was Anthropic-only). Degrades to *unscored* on judge failure rather than crashing.
- **Scorecard** (`evals/scorecard.py`): weighted per-`(model×harness)` grade across
  **WORKFLOW** (accuracy, completion) and **MCP-COMPATIBILITY** (tool-use, clean calls,
  efficiency); reads saved results, recomputes everything but accuracy from the runs (no model
  calls), and **guards comparability** (flags rows scored on different task sets).

Key finding the matrix cleanly separates: a strong model via the Claude Code persona scores
accuracy 1.0 but **tool_use 0.0** — it answers well-known objects from memory and skips the
server (COMPAT drops); the same harness pointed at Qwen scores tool_use 1.0. So (model ×
harness) genuinely matters, and the scorecard surfaces it.

## Pillar 3 — archive caveat regression (keep the KB honest) — **SHIPPED**

`evals/caveats.py`. Model-free, deterministic, independent of Pillars 1–2. Each `Caveat` is
a falsifiable claim from the KB paired with a small live ADQL probe and an expected outcome
(`ok` / `error` / `empty`), keyed to `(archive, caveat_id)`. Verdicts: **STILL-TRUE / STALE /
UNREACHABLE**; a STALE result names the archive + caveat to edit. `--list`, `--archive <x>`,
non-zero exit on any STALE (cron/CI-friendly).

**STALE vs UNREACHABLE** is separated by a per-archive **control probe** (a metadata query
that must work if the service is up). If the control fails → the archive is UNREACHABLE and
its caveats aren't judged, so a network blip is never misreported as "the KB went stale".
Only when the control passes is a caveat that behaves opposite to its claim called STALE.
Uses the package's own `TapClient` + error taxonomy (`DalQueryError` = semantic reject,
`ArchiveError` = service).

8 caveats across datalab / nrao / alma / gaia / eso / cadc (e.g. Data Lab geometry still
untranslated + `q3c_radial_query(...)='t'` still works; NRAO `/sync` still 5xxs on
`tap_schema.obscore`; `ivoa.obscore` still absent; `dataproduct_subtype` still absent; ALMA
sync-spatial still works). Validated live: datalab 2/2 and nrao 3/3 STILL-TRUE.

### Step 0 (KB per-archive modularization) — **deliberately skipped**

The original plan made a `src/` refactor (split `known_archives.py` / `schema_kb.py` into
per-archive modules) a prerequisite, to give each caveat a stable home for a 1:1 check↔note
mapping. **We got that mapping without the refactor:** keying each `Caveat` by
`(archive, caveat_id)` in `evals/caveats.py` already points a STALE result at the exact note,
and the caveat probes live in `evals/` (out of the default `pytest` run) — the parallel
structure the open question leaned toward. The `src/` refactor was risk (touches shipping
code, 285 tests to re-green) with no added Pillar-3 value, so it was not done. Revisit only
if `known_archives.py` / `schema_kb.py` grow unwieldy for their own sake — as a separate,
behavior-preserving change, not gated on the eval work.

## Cross-cutting dependencies / notes

- **Credentials (resolved for the built scope):** config lives in gitignored `evals/.env`
  (committed `evals/.env.example` documents the scheme), auto-loaded by `evals/_env.py`.
  Model under test = dlai01 Qwen3.5 via the datalab proxy + Basic auth (free, self-hosted).
  Judge = hosted Claude Haiku 4.5 (`EVAL_JUDGE_*`, ~pennies/run, ~100% verdict parse) or free
  Qwen (flakier JSON). To broaden Pillar 2 to OpenAI models, add an OpenAI key with
  `EVAL_MODEL_BACKEND=openai`. Persona@hosted-Claude bills the user's Claude account (use
  `--limit`); persona@Qwen is free.
- Eval runs are **live-network + real-model** → slow and non-hermetic. They live in `evals/`,
  out of the default `pytest` run. The caveat suite is model-free but still live-network.
- **Open bug (filed separately):** `vo_registry_describe` can return ~127k tokens on a large
  service (Gaia) and blow the model's context window — cap it in
  `shape_registry_describe_result` (branch `dpg/registry-describe-catalog`). Pillar 1
  independently re-surfaced and priced this in a workflow.

## Follow-ups (not yet done)

- **Wire the caveat suite to a cron** for over-time monitoring (the runner already exits
  non-zero on STALE — just needs scheduling).
- **Grow the caveat set** as `usage_notes` grow — every new falsifiable claim should get a
  probe. Currently 8; the KB has more claims that are async-only or not cleanly probeable.
- **Register more personas** once other agent CLIs are installed (Gemini CLI, Goose, Codex) —
  one `PERSONA_REGISTRY` entry each.
- Act on the Pillar-1 refinement leads: **#41** (ESO usage_notes), **#42** (CADC DataLink
  follow-through).
