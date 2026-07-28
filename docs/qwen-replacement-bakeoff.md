# Qwen Replacement Bake-off — Log

**Driver:** policy — no Chinese open-weight models. Qwen3.5-122B-A10B-FP8 taken
down (date recorded below); replacement selected from three candidates by the
gates below. Spec + survey rationale: see the design doc (out-of-repo,
superpowers/specs/2026-07-27-qwen-replacement-bakeoff-design.md).

## Serving setup (all candidates)

dlai01, GPUs 0-2, vLLM compose (`deploy/dlai01-vllm/`), 131072-token window:

    cd ~/sbx/manna/deploy/dlai01-vllm
    docker compose --env-file candidates/<name>.env up -d

vLLM image: `vllm/vllm-openai:latest` pulled 2026-07-28 =
`sha256:ffb2d59b1c059a5bd8d781320c9f5189de8293693b7d95da54befddaa54abf52` (vLLM 0.26.0)
— this digest is the cutover pin. Verified against its parser registration tables
(0.26's condensed `--help` no longer lists them; registries fill lazily): tool parsers
`qwen3_coder`, `openai`, `gemma4` and reasoning parsers `qwen3`, `nemotron_v3`,
`openai_gptoss`, `gemma4` all present — every candidates/*.env value is valid as-is.
NB: `--no-trust-remote-code` acceptance couldn't be pre-verified (arg-parser
construction needs a GPU, blocked below); it is implicitly verified at each
candidate's gate 1 boot.

**BLOCKER (2026-07-28, IT ticket filed):** all new GPU containers on dlai01 fail —
stale CDI spec `/var/run/cdi/nvidia.yaml` (generated Jun 29 09:11:21 during the
nvidia-container-toolkit 1.19.1 install; box last booted Jun 22) references
`libnvidia-egl-wayland.so.1.1.21`, removed in the Jul 23 patch window (successor
`libnvidia-egl-wayland2.so.1.0.1`; ldcache clean). Reproduced image-independently
(`--gpus all alpine true` fails identically); host `nvidia-smi` healthy (610.43.02).
Fix is root-only: `nvidia-ctk cdi generate --output=/var/run/cdi/nvidia.yaml`.
Would have killed the production service on its next restart regardless — surfaced
during the planned takedown with GPUs idle. Weight pre-pulls (GPU-free) proceeding
meanwhile. See runbook Gotcha 7.

## Gates (ordered; each blocks the next)

1. **Boot clean** — startup config line shows both parsers; healthcheck green.
2. **/v1/messages smoke** — proper `{"type":"message",...}` envelope.
3. **Tool call fires** — persona resolves M51 via `vo_target_resolve`;
   `grep -c CallToolRequest ~/sbx/mcp.log` ≥ 1.
4. **Reasoning containment** — with `output_config.effort=high`, reasoning lands
   in `thinking` blocks, never reply `content`; tool calls still fire with
   reasoning on.
5. **Evals scorecard** — standard evals run over the datalab proxy; scores below.
6. **Concurrency sanity** — 8 parallel /v1/messages requests at agentic context
   lengths; no `<pad>`/garbling; note aggregate tok/s.

## Eval env per candidate (run from laptop; Basic-auth creds as usual)

    export EVAL_MODEL_NAME=<checkpoint id>     # e.g. openai/gpt-oss-120b
    export EVAL_MODEL_LABEL=<label>            # e.g. gpt-oss-120b
    # endpoint + auth: see evals/.env.example
    uv run python -m evals.run              # tiers 1-4
    uv run python -m evals.mcp_quality
    uv run python -m evals.persona_run
    # see evals/README.md for details on each entrypoint

## Results

### Qwen takedown

- Date/time: 2026-07-28 (via Keeper session; after PR #75 merge)
- Final `docker compose down` output: `docker compose --env-file candidates/qwen3.5.env down`
  → `Container vllm Removed` + `Network dlai01-vllm_default Removed`; `docker ps` empty;
  `nvidia-smi` 0 MiB on all four GPUs. (Bare `compose down` correctly refused on the
  `:?` guard — the rollback env file is the documented path.)

### Candidate: nemotron3-super

| Gate | Result | Notes |
|---|---|---|
| 1 boot | | parallelism ladder attempts: |
| 2 messages | | |
| 3 tool call | | |
| 4 reasoning | | |
| 5 evals | | scorecard: |
| 6 concurrency | | |

### Candidate: gpt-oss-120b

| Gate | Result | Notes |
|---|---|---|
| 1 boot | | |
| 2 messages | | |
| 3 tool call | | |
| 4 reasoning | | |
| 5 evals | | scorecard: |
| 6 concurrency | | |

### Candidate: gemma4-31b

| Gate | Result | Notes |
|---|---|---|
| 1 boot | | |
| 2 messages | | |
| 3 tool call | | |
| 4 reasoning | | |
| 5 evals | | scorecard: |
| 6 concurrency | | #39392 outcome: |

## Decision

Selection rule: scorecard first; decode latency + concurrency headroom second
(gp13 multi-user rollout); license permissiveness as tiebreaker.

- **Winner:** <fill>
- **Rationale:** <fill>
- Dan sign-off date: <fill>
