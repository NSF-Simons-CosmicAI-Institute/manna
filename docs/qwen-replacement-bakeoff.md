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
`libnvidia-egl-wayland.so.1.1.21`, removed root-side sometime between Jul 21 (last
successful container create) and Jul 28, with no RPM trace — what removed it is
unresolved, IT to determine (successor `libnvidia-egl-wayland2.so.1.0.1` present;
ldcache clean). Reproduced image-independently
(`--gpus all alpine true` fails identically); host `nvidia-smi` healthy (610.43.02).
Fix is root-only: restart/enable the `nvidia-cdi-refresh` units (or `nvidia-ctk cdi
generate --output=/var/run/cdi/nvidia.yaml`); MUST also ensure the refresh units are
enabled — /var/run is tmpfs, so a disabled refresh means the spec vanishes at next
reboot and GPU containers break again. Diagnosis independently verified (adversarial
review, 2026-07-28): direct cause CONFIRMED; exact removal event unproven.
Would have killed the production service on its next restart regardless — surfaced
during the planned takedown with GPUs idle. Weight pre-pulls (GPU-free) proceeding
meanwhile. See runbook Gotcha 7.

**RESOLVED (2026-07-28):** IT patched + rebooted (kernel, docker-ce 29.6.2,
containerd.io 1.x→2.2.6) with the CDI regeneration. The containerd major upgrade then
orphaned the old image store (known containerd#11719 class): every create failed with
`rename .../snapshots/NN: file exists`, image DB knew nothing of ~40G on the volume.
No root needed for recovery: each failed attempt deletes exactly the one colliding
leftover dir (verified mechanism, adversarial review), so retry loops chewed through
~30 leftovers until `docker run --rm --gpus all alpine:3.21 true` printed GPU-OK —
which also confirmed the CDI fix. Residue: ~40G orphaned blobs on the containerd
volume, invisible to prune; flagged for cleanup in a future maintenance window.
vLLM image re-pulled by pinned digest. Weight caches on /mlhome unaffected throughout.

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
| 1 boot | PASS | Ladder: TP=3 refused (32 heads % 3 != 0, same as Qwen) -> PP=3/TP=1 booted clean; vLLM 0.26 auto-split the 88 hybrid layers unevenly. ~45 GiB KV/GPU (fp8 KV auto-enabled by model config), warmup 118 s |
| 2 messages | PASS | Proper Anthropic envelope on loopback :8002; reasoning already routed to a `thinking` block |
| 3 tool call | PASS | Persona resolved M51 = RA 202.469575 / Dec +47.19525833 via vo_target_resolve on the local MCP (manna v0.5.0); clean reply text |
| 4 reasoning | PASS | effort=high -> ['thinking','text'], text block clean (17*23=391), no leak |
| 5 evals | 0.643 | Tiers 1+2 on-box loopback, self-judge. tier1 0.857 (6/7; t1-schema failed on vo_schema_describe arg flailing), tier2 0.429 (3/7; 1 async upstream latency, 2 hit 20-step cap). 2.0 tool-calls/task, 32.1 s/task, 10323 output tokens. results/run-20260728T112653.json |
| 6 concurrency | | |

Eval-run note (applies to all candidates): proxy 502 since the dlai01 reboot
(nginx-side, Chadd/Randy) forced evals onto dlai01 loopback — better anyway
(no proxy noise); all candidates measured identically this way.

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
