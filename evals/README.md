# evals/ — agentic evaluation harness

Measures how well a real LLM (the dlai01 vLLM **gpt-oss-120b** by default) uses this
server's MCP tools to answer astronomer tasks — and whether the server's curated
context actually earns its keep.

The suite is organized in four tiers: **1** tool-selection accuracy (single intent, no
chaining), **2** multi-step task success (real workflows), **3** a context ablation that
runs each trap task with and without the server's curated `usage_notes` + schema KB to
measure trap avoidance, and **4** robustness/safety (error recovery, unknown archives,
async-job polling, and leak checks).

This is **not** part of the shipped server. It lives outside `tests/` because eval
runs are **live-network** (they hit the real archives to measure real correctness)
and drive a real model, so they are slow and non-hermetic by design.

## What it does

```
task prompt ─► model under test (Anthropic Messages API)  ─► emits tool_use
                                                              │
                          Client(build_mcp()) executes ◄──────┘  (live archives)
                          tool_result fed back; loop to final answer
                                     │
                          score.py grades the recorded trace + answer
```

- **`tasks.yaml`** — the versioned task suite (4 tiers, above). The review target.
- **`harness.py`** — the agent loop + model config (`ModelConfig.from_env`).
- **`context.py`** — the Tier-3 ablation: strips `usage_notes` + the schema KB so we can
  compare trap-avoidance **with vs. without** curated context.
- **`score.py`** — programmatic checks (tools, order, args, ground truth, safety scan)
  plus an optional LLM judge for open-ended `rubric` tasks.
- **`run.py`** — CLI; aggregates metrics and writes `results/<timestamp>.json`.
- **`_env.py`** — loads `evals/.env` into the process at startup (dependency-free,
  `.env`-style parsing) so entrypoints that need model/judge credentials don't need a
  manual `source`.
- **`_common.py`** — glue shared by the eval CLIs: judge config, results-file writing,
  small math helpers.
- **`exp_a_matrix.py`** — the discovery × description-injection experiment matrix (cells
  A/C/D) measuring whether curated archive quirks still reach the model when it can't
  (or won't) call the discovery tools.
- **`rejudge.py`** — re-scores a saved results file's `rubric` tasks with a (possibly
  different) judge model, without re-running the agent loop.
- **`selftest.py`** — offline self-test of the scoring/ablation machinery (`score.py` +
  `context.py`); no model calls, no network. Because it never contacts the model it
  **cannot** tell you whether `EVAL_MODEL_NAME` is still valid — a green selftest with a
  stale model name is expected, not reassuring. `run.py` covers that with a preflight.

### Model preflight

`run.py` checks `EVAL_MODEL_NAME` / `EVAL_JUDGE_NAME` against the endpoint's
`/v1/models` before running anything, and exits 2 with the served list if a name is
gone. This exists because the proxy's model changed (Qwen → gpt-oss) while `evals/.env`
kept the old name: every task then failed with an opaque
`NotFoundError: The model ... does not exist` partway through a run, which looks like a
MANNA regression rather than a config problem.

Only a *positive* absence blocks a run. A hosted endpoint (no `base_url`), an
unreachable host, or an unrecognised payload all pass through — absence of evidence
never fails the run.

## Install

```bash
uv sync --group eval        # adds anthropic + pyyaml (server runtime deps untouched)
```

## Configure the model + judge

Copy the template and fill in real values — it's **gitignored** and auto-loaded by every
eval entrypoint (no `source` needed; real shell env vars still override it):

```bash
cp evals/.env.example evals/.env    # then edit evals/.env
```

| Var | Purpose |
|-----|---------|
| `EVAL_MODEL_NAME` / `_BASE_URL` / `_API_KEY` / `_CUSTOM_HEADERS` | the **model under test** (dlai01 gpt-oss-120b via the datalab proxy) |
| `EVAL_MODEL_BACKEND` (+ `EVAL_JUDGE_BACKEND`) | wire shape: `anthropic` (default) or `openai` |
| `EVAL_JUDGE_NAME` / `_API_KEY` (+ `_BASE_URL` / `_CUSTOM_HEADERS`) | the rubric **judge** |
| `EVAL_MAX_STEPS` / `EVAL_ASYNC_POLL_SLEEP` | optional run knobs |

The judge config is **independent** of the model-under-test (it does *not* inherit the
proxy `ANTHROPIC_*`/`EVAL_MODEL_*` vars), so a **hosted Claude Haiku** judge (`EVAL_JUDGE_NAME=claude-haiku-4-5-20251001`
+ a real `EVAL_JUDGE_API_KEY`) stays cleanly separated from a local-proxy model. The
**free self-hosted judge** (the served model judges itself — fine for smoke runs, never
for real numbers) (~75–85% JSON-parseable) is the zero-cost fallback. Never let the model
grade itself for real numbers; if no judge is set, rubric tasks report as *unscored*
(never silently passed). (`EVAL_MODEL_*` also still falls back to the persona's bare
`ANTHROPIC_*` vars if you prefer to reuse `deploy/frontend/.env`.)

## Run

```bash
uv run python -m evals.run --dry-run          # validate tasks.yaml, no model calls
uv run python -m evals.run --tier 1 --tier 2  # tool-selection + task-success
uv run python -m evals.run --tier 3           # ablation: with vs. without context
uv run python -m evals.run --task t2-resolve-cone   # a single task
uv run python -m evals.run                    # full suite
```

Tier-3 tasks (and `--condition both`) run twice — full vs. ablated — and the report
prints the **trap-avoidance delta**, the headline "is this server worth it" number.
Keep `--concurrency` low (default 3) against a single-GPU-hosted model.

## Clean-state run recipe (dlai01)

Stale persona env exports (`ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_API_KEY`,
`ANTHROPIC_DEFAULT_*_MODEL`) left over from a Claude Code persona session hijack the judge
SDK client — the judge silently starts talking to the local proxy instead of the real
Anthropic API. Before a real run, start from a fresh shell or explicitly unset them:

```bash
unset ANTHROPIC_BASE_URL ANTHROPIC_AUTH_TOKEN ANTHROPIC_API_KEY ANTHROPIC_DEFAULT_OPUS_MODEL \
      ANTHROPIC_DEFAULT_SONNET_MODEL ANTHROPIC_DEFAULT_HAIKU_MODEL
```

Then set up `evals/.env` with `EVAL_MODEL_*` pointed at the local vLLM and a real judge
(judge ids need the full dated form, e.g. `EVAL_JUDGE_NAME=claude-haiku-4-5-20251001`).
Run in the background and tail progress:

```bash
nohup uv run --group eval python -m evals.run --tier 1 --tier 2 > eval.log 2>&1 &
grep -cE '\[(PASS|FAIL)\]' eval.log   # poll progress
```

## Adding a task

Append to `tasks.yaml` following the schema documented at the top of that file. Prefer a
deterministic `ground_truth` (coords/contains/regex) when the answer has a stable correct
value; use a `rubric` (judge-scored) only for open-ended answers. For a Tier-3 trap,
express "avoided the trap" as `arg_checks` on the recorded ADQL/args (e.g. `mode == async`,
or ADQL `not_contains CONTAINS(`) so it scores without a judge.

## Three evaluation programs

Beyond the tier suite above, `evals/` hosts three focused programs.

**1 — MCP quality** (`mcp_quality.py`): is the server *worth it*? Runs a task suite
(`mcp_quality_tasks.yaml`) through 3 arms — `mcp` (the tools) vs `raw_tap` vs `raw_web`
(`providers.py`) — and reports accuracy / tool-errors / iterations per arm, with per-tool /
per-archive breakdown and version-over-version diffing against a baseline.

```bash
uv run python -m evals.mcp_quality                 # 3-arm comparison
uv run python -m evals.mcp_quality --set-baseline  # record results/mcp-quality-baseline.json
```

> **Metric change (2026-07):** `tool_error_calls` now counts the server's
> error-as-payload results (`error_class` present), which the mcp arm
> previously could never register. Re-record baselines (`--set-baseline`)
> before trusting version-over-version diffs that span this change.

**2 — model × harness matrix** (`model_backends.py`, `personas.py`, `persona_run.py`,
`scorecard.py`): how well do different **models** and **harnesses** work with the server?
`make_backend` drives Anthropic (Messages) **or** OpenAI (Chat Completions) models via one
neutral path (`EVAL_MODEL_BACKEND`); `make_persona` drives a real agent harness (Claude Code
today; a registry, so add a driver in one entry) end-to-end and scores its transcript.
`scorecard.py` grades each `(model × harness)` cell on WORKFLOW + MCP-COMPATIBILITY axes.

```bash
uv run python -m evals.persona_run --limit 3               # Claude Code persona, 3 tasks
uv run python -m evals.persona_run --same-model --limit 3  # persona at the same dlai01 model (free)
uv run python -m evals.scorecard evals/results/mcp-quality-*.json evals/results/persona-*.json
```

**3 — archive note regression** (`audit.py`): keep the KB honest. **Model-free** — one
live ADQL probe per each probeable `Note` audit, keyed to `archives/<archive>.py ::
<note_id>`, reporting STILL-TRUE / STALE / ENDPT-DEAD / UNREACHABLE. Notes whose claims
a single ADQL probe can't check are tagged MANUAL and listed for hand-verification —
run `--list` for the current probeable/manual split, and prefer a probeable `Audit`
whenever one exists (the one stale note the 2026-07 audit found was hiding in the
manual pile). Non-zero exit on STALE or ENDPT-DEAD (cron/CI-friendly).

```bash
uv run python -m evals.audit --list          # list notes, no probes
uv run python -m evals.audit --archive nrao  # one archive
uv run python -m evals.audit                 # all notes vs live archives
```
