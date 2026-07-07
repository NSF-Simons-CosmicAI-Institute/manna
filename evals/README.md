# evals/ — agentic evaluation harness

Measures how well a real LLM (the dlai01 vLLM **Qwen3.5** by default) uses this
server's MCP tools to answer astronomer tasks — and whether the server's curated
context actually earns its keep. Design: [`docs/mcp-eval-plan.md`](../docs/mcp-eval-plan.md).

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

- **`tasks.yaml`** — the versioned task suite (4 tiers; see the plan). The review target.
- **`harness.py`** — the agent loop + model config (`ModelConfig.from_env`).
- **`context.py`** — the Tier-3 ablation: strips `usage_notes` + `schema_kb` so we can
  compare trap-avoidance **with vs. without** curated context.
- **`score.py`** — programmatic checks (tools, order, args, ground truth, safety scan)
  plus an optional LLM judge for open-ended `rubric` tasks.
- **`run.py`** — CLI; aggregates metrics and writes `results/<timestamp>.json`.

## Install

```bash
uv sync --group eval        # adds anthropic + pyyaml (server runtime deps untouched)
```

## Configure the model

The harness reads the **same `ANTHROPIC_*` env the Jupyter AI persona uses**, so the
`deploy/frontend/.env` that runs the persona also runs the eval. Overrides use the
`EVAL_MODEL_*` prefix.

| Var | Purpose | Fallback |
|-----|---------|----------|
| `EVAL_MODEL_NAME` | served model name | `ANTHROPIC_DEFAULT_OPUS_MODEL` |
| `EVAL_MODEL_BASE_URL` | endpoint (omit for hosted Claude) | `ANTHROPIC_BASE_URL` |
| `EVAL_MODEL_API_KEY` | auth token (`dummy` for vLLM) | `ANTHROPIC_API_KEY` |
| `ANTHROPIC_CUSTOM_HEADERS` | e.g. `Authorization: Basic <b64>` | — |

For the rubric **judge**, set `EVAL_JUDGE_NAME` (+ its own `EVAL_JUDGE_*`). Use hosted
Claude here — never let the model under test grade itself. If no judge is configured,
rubric tasks are reported as *unscored* (not silently passed).

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

## Adding a task

Append to `tasks.yaml` following the schema documented at the top of that file. Prefer a
deterministic `ground_truth` (coords/contains/regex) when the answer has a stable correct
value; use a `rubric` (judge-scored) only for open-ended answers. For a Tier-3 trap,
express "avoided the trap" as `arg_checks` on the recorded ADQL/args (e.g. `mode == async`,
or ADQL `not_contains CONTAINS(`) so it scores without a judge.
