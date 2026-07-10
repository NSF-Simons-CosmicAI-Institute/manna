# Evaluation & QA program for astro-archives-mcp

Status: **roadmap / design reference** — meant to be read at the start of any session
that works on evaluation. Only Pillar 1's *foundation* is built so far (see below).
Companion docs: `docs/mcp-eval-plan.md` (the 4-tier task design + first-run findings),
memory `eval-harness-findings` (results vs. live Qwen3.5).

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

## Current foundation (what already exists)

Branch `dpg/mcp-eval-harness` (worktree `../astro-archives-mcp-eval`, merged up to `dev`).
`evals/` contains a working agentic harness:

- **`harness.py`** — agent loop; drives a model via the **Anthropic Messages API** (works
  for Anthropic models *and* open-weights served by vLLM) against an in-memory
  `Client(build_mcp())` with **live archives**. Records the full trace (tool calls, args,
  results, final answer), **tokens, iterations (steps + tool-calls), latency**.
- **`tasks.yaml`** — 24 tasks in 4 tiers (tool-selection, task-success, contextual-value
  ablation, robustness/safety).
- **`score.py`** — programmatic checks (tools / order / args / ground-truth / leak scan) +
  an optional **LLM judge** for open-ended rubric tasks.
- **`run.py`** — CLI + metric aggregation. **`context.py`** — with/without curated-context
  ablation. Measurement **levers already built**: context ablation, `--no-discovery`
  (withhold `vo_archive_list`/`vo_schema_describe`), `--inject-notes` (put quirks in the
  tool description). **Do not trim these — they are Pillar-1 levers.**

Reframe needed to serve all three: **Driver (model-adapter × harness) → Trace →
Rubric/Scorer**, plus a **separate, model-free caveat suite**. The current harness is the
first Driver; most new work hangs off that seam.

## Pillar 1 — MCP quality (refine the server)

**Decision (locked):** measure **both** (a) a **no-VO-tools A/B baseline** — same task with
the MCP tools vs. an agent given only raw HTTP/ADQL (or nothing) — for the headline "is the
server worth it" lift in iterations/tokens/accuracy; **and** (b) **version-over-version
tracking** of those metrics so refinements to tools/notes visibly move the numbers.

- Have: iteration/token/latency/success capture; ablation + tool-withholding levers.
- Need: the no-VO-tools baseline driver; more **download**-oriented tasks (SIA fetch /
  resource retrieval is thin); **run-to-run diffing** + per-tool / per-archive breakdown
  reporting so the refine loop is legible.

## Pillar 2 — model / harness matrix + rubric

**Decision (locked):** include **real ACP personas** (Claude Code, Gemini CLI, Goose,
Codex) as drivers — not just the custom loop.

- **Model-adapter layer:** Anthropic Messages API (have). **Need** an **OpenAI-compatible**
  adapter → covers OpenAI models *and* most open-weights served via OpenAI-style endpoints.
- **Harness drivers:** custom loop (have). **Need** real-**persona** drivers — launch the
  persona with the MCP server registered, capture and score its transcript. This is the
  scored generalization of `deploy/frontend/.../smoke-test.sh` (which today just greps for
  M51 coords). Biggest lift in the program.
- **Rubric / scorecard:** a weighted per-`(model, harness)` scorecard across two axes:
  (a) **MCP compatibility** — valid tool calls, correct params, error recovery per
  `retry_strategy`, wasted/looping calls; (b) **end-to-end workflow success** — reached the
  correct answer (ground-truth or judge). Formalize from the current tiers (Tier 1 ≈ tool
  mechanics, Tier 4 ≈ compatibility, Tier 2/3 ≈ workflow).
- Need: OpenAI adapter; ACP-persona driver(s) + transcript parsing; the formal
  rubric+scorecard; **provider credentials** (see dependencies).

## Pillar 3 — archive caveat regression (keep the KB honest)

Model-free, deterministic, independent of Pillars 1–2 — and the cheapest / highest
ROI-per-effort. **One check per caveat**, keyed to its `known_archives.usage_notes` /
`schema_kb` entry, using the `backends/` clients. Each returns **still-true / STALE /
unreachable**; a STALE result should name the exact note to edit. Run on a **cron schedule**
for over-time monitoring.

Example checks (from current KB):
- NRAO `/sync` still 5xxs on a trivial `tap_schema.obscore` read (async still required).
- NRAO obscore is at `tap_schema.obscore`, not `ivoa.obscore`.
- Data Lab ADQL geometry (`CONTAINS`/`CIRCLE`) still errors; `q3c_radial_query(...)='t'`
  still works (this one already drifted once — see the merge-with-dev reconciliation).
- `LOWER`/`UPPER` still fail on NRAO.
- ALMA obscore rows still at spectral-window granularity (`member_ous_uid` still the key).

Design note: needs a small structure tying each check to its KB source so failures point
straight at the note/field to update.

## Cross-cutting dependencies / notes

- **Credentials are a gating blocker for Pillar 2 breadth + a stronger judge.** So far only
  a Claude Code **OAuth** token is available (wrong type for the raw Messages API, and the
  harness classifier blocks using it). Need: an **Anthropic API key**, an **OpenAI key**,
  and the **open-weights serving endpoint(s)**. The dlai01 vLLM (Qwen3.5) works today via
  the datalab proxy + Basic auth (`deploy/frontend/.env`).
- Eval runs are **live-network + real-model** → slow and non-hermetic. Keep them in
  `evals/` (and a future `evals/caveats/`), out of the default `pytest` run.
- **Open bug to fix separately:** `vo_registry_describe` can return ~127k tokens on a large
  service (Gaia) and blow the model's context window — cap it in
  `shape_registry_describe_result`. (Handoff write-up already produced; being done in a
  separate session.)

## Suggested phasing (not locked)

1. **Pillar 3 (caveats)** — cheap, independent, immediately keeps the KB honest.
2. **Pillar 1** — no-tools baseline + metrics/diffing to quantify and drive refinement.
3. **Pillar 2** — model adapters + rubric first, then the real ACP-persona drivers.
