# dlai01 Model-Hosting — Validation Record & Runbook

**What this documents:** hosting an open-weight LLM (Qwen3.5) on the dlai01 GPU box
via vLLM, and consuming it from a Claude Code persona that calls the MANNA
**MCP** tool server — the full local-model chain, proven end to end. Exact working
commands, verified results, and every gotcha we hit.

Paired with `docs/jupyter-ai-integration.md` (the persona/MCP architecture).
Status: **local chain
VALIDATED** and **exposed off-box via the datalab nginx proxy (2026-07-02)** — reachable
from a laptop and from the dockerized frontend (see *Current status* at the end).

---

## Architecture

Two hosts, split backend/frontend:

- **dlai01** — the **backend / model host**: 4× RTX PRO 6000 Blackwell, runs vLLM
  serving the LLM. Where the GPUs and docker access live.
- **gp12** — the production **frontend**: a shared JupyterHub running Jupyter AI + the
  Claude Code persona per user. (Not yet accessible; the MCP server + a JupyterHub are
  being stood up locally first as a gp12 stand-in.)

The chain, and the two independent connections the persona makes:

```
JupyterLab (Jupyter AI v3)
      │
      ▼
 ACP persona = Claude Code ──(model)──► vLLM  [ANTHROPIC_BASE_URL]      ← dlai01
      │
      └─────────────────────(tools)──► MANNA MCP  [/mcp/]               ← colocated
```

- **Model** and **tools** are orthogonal: the `vo_*` tools work identically no matter
  which model backs the persona (hosted Claude or local vLLM).
- The persona talks to the model over the **Anthropic Messages API** — vLLM implements
  it natively, so **no translation proxy** is needed.

## The box (dlai01)

- Rocky Linux 10, **4× RTX PRO 6000 Blackwell** ~96 GB ea (~384 GB total), **sm_120**,
  driver 610.43.02 / CUDA UMD 13.3.
- User `dgause`: in the `docker` group, **no sudo / no host software installs** →
  everything runs in containers.
- GPU-in-container verified (`docker run --gpus all … nvidia-smi -L` lists all 4).

## What's validated

| Date | Milestone |
|------|-----------|
| 2026-06-29 | MCP server rootless on dlai01; persona chain proven with **hosted Claude** (headless `claude -p`, M51 resolved via `vo_target_resolve`). |
| 2026-06-30 | **Local-model plumbing** proven — Qwen2.5-7B on vLLM (sm_120 works out of the box; native `/v1/messages`; tool call fired). |
| 2026-07-01 | **Production model** proven — **Qwen3.5-122B-A10B-FP8**, TP=4, resolved M51 (RA 202.469575 / Dec +47.19525833 ICRS) via a real tool call. |
| 2026-07-21 | **3-GPU scale-back** proven — same model on **PP=3 / TP=1** (device_ids 0–2), freeing GPU 3. Booted clean (`world_size=3`, per-stage ~39.9 GiB, KV 44.78 GiB/GPU, 131072 window intact). See "Scaling GPU count" below. |

## Prerequisites (resolved by IT, 2026-06-29)

All in-container; no host installs needed from us.

1. **Docker image storage on real space.** The vLLM image is ~20 GB extracted; the
   default docker fs was 16 GB → `no space left on device`. **Subtlety that cost a
   round-trip:** this box uses Docker's **containerd image store**
   (`Storage Driver: overlayfs`), so image layers land in **`/var/lib/containerd`**,
   *not* the `/var/lib/docker` reported as "Docker Root Dir". Growing `/var/lib/docker`
   did nothing; the fix was giving `/var/lib/containerd` its own 250 GB volume. **If you
   ever hit this again, check `df -h /var/lib/containerd`.**
2. **Writable weights dir** — `/mlhome/dgause` (7 TB NVMe), owned by `dgause`, for the
   HF cache (`-v /mlhome/dgause/hf:/root/.cache/huggingface`).
3. **nvidia-container-toolkit** installed → GPU passthrough into containers.

---

## Part 1 — the MCP tool server

Runs rootless via `uv` on loopback (read-only VO tools; no auth needed on loopback).

```bash
cd ~/sbx/astro-archives-mcp   # (rename this checkout to ~/sbx/manna when the repo is renamed)
export PATH="$HOME/.local/bin:$PATH" XDG_CACHE_HOME="$HOME/.cache"   # writable astropy/tmp cache
nohup env MANNA_PORT=8000 uv run python -m manna > ~/sbx/mcp.log 2>&1 &
curl -fsS http://127.0.0.1:8000/health        # {"status":"ok","version":"0.5.0",...}
```

Register it with Claude Code — **user scope is required** (see Gotcha 3):

```bash
CLAUDE_CONFIG_DIR=$HOME/.claude-work \
  claude mcp add --scope user --transport http manna http://127.0.0.1:8000/mcp/
CLAUDE_CONFIG_DIR=$HOME/.claude-work claude mcp list       # manna: ✓ Connected
```

## Part 2 — hosting the model on vLLM

**Model: `Qwen/Qwen3.5-122B-A10B-FP8`** (122B total / ~10B active MoE). Chosen for
near-top open-weight BFCL V4 (~0.722), fits FP8 (~122 GB) with large KV-cache headroom,
MoE decode is fast and concurrency-friendly. Tool-call parser: `qwen3_coder`. Runner-up to A/B later:
**GLM-4.7** (τ²-Bench 87.4, but 358 GB FP8 leaves little KV room → poor concurrency).

> The lighter **Qwen2.5-7B-Instruct** (parser `hermes`, `--max-model-len 32768`) is the
> de-risking PoC — same command, smaller model — used 2026-06-30 to prove vLLM runs on
> sm_120 and the Anthropic path carries tool calls before committing to the big download.

Launch (weights cache to `/mlhome`; ~122 GB pull first time, then loads from cache).
**For day-to-day operation prefer the durable compose service** (`dlai01-vllm/docker-compose.yml`,
`restart: unless-stopped` — survives reboots): `cd deploy/dlai01-vllm && docker compose up -d`.
The raw `docker run` below is the equivalent one-shot for reference / first bring-up:

```bash
docker rm -f vllm 2>/dev/null
docker run -d --name vllm --gpus all --ipc=host \
  -v /mlhome/dgause/hf:/root/.cache/huggingface \
  -p 127.0.0.1:8001:8000 \
  vllm/vllm-openai:latest \
  --model Qwen/Qwen3.5-122B-A10B-FP8 \
  --tensor-parallel-size 4 \
  --enable-auto-tool-choice --tool-call-parser qwen3_coder \
  --max-model-len 131072
docker logs -f vllm            # wait for "Application startup complete" (~130 s)
```

> **`--max-model-len` sizing (updated 2026-07-02).** Originally `65536`; agent loops that
> accumulate tool results overflowed it (see Gotcha 4c). Raised to **131072**. First verify
> the checkpoint's native limit — `docker exec vllm python -c "import json,glob; \
> print(json.load(open(glob.glob('/root/.cache/huggingface/**/config.json',recursive=True)[0]))['max_position_embeddings'])"` —
> if it's below your target you'd need `--rope-scaling` (YaRN), unvalidated here. Watch KV
> memory on startup (`GPU KV cache size` in the logs); the box has headroom but a larger
> window costs cache.

Notes / verified behavior:
- **sm_120 works out of the box** on `vllm/vllm-openai:latest` (vLLM **v0.23.0**) —
  FlashAttention 2, FlashInfer, torch.compile, CUDA graphs all initialize; no special
  tag/recipe. Arch resolves as `Qwen3_5MoeForConditionalGeneration`.
- **Native Anthropic endpoint present:** `Route: /v1/messages` is in the served route
  list and returns a proper `{"type":"message",...,"stop_reason":"end_turn"}` — **no
  proxy**. Quick check:
  ```bash
  curl -s http://127.0.0.1:8001/v1/messages -H 'content-type: application/json' \
    -d '{"model":"Qwen/Qwen3.5-122B-A10B-FP8","max_tokens":64,"messages":[{"role":"user","content":"hi"}]}'
  ```
- **Benign multi-GPU warnings on sm_120** (not errors): `SymmMemCommunicator: Device
  capability 12.0 not supported` and `Custom allreduce is disabled … PCIe-only GPUs` →
  both fall back to NCCL.
- **`--reasoning-parser=qwen3` IS set** — it is the fix for the `<think>` leak into reply
  `content`; see Gotcha 5. (It was historically omitted; that lore is retired.)

## Part 3 — consuming it (the Claude Code persona)

The persona reads its endpoint from env; point it at vLLM and run the validation. Use a
**scoped tool allowlist**, not `--dangerously-skip-permissions` (Gotcha 2):

```bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:8001
export ANTHROPIC_AUTH_TOKEN=dummy                 # any value while on loopback; a real secret once exposed
export ANTHROPIC_DEFAULT_OPUS_MODEL=Qwen/Qwen3.5-122B-A10B-FP8
export ANTHROPIC_DEFAULT_SONNET_MODEL=Qwen/Qwen3.5-122B-A10B-FP8
export ANTHROPIC_DEFAULT_HAIKU_MODEL=Qwen/Qwen3.5-122B-A10B-FP8
export CLAUDE_CODE_MAX_OUTPUT_TOKENS=8192          # REQUIRED — Gotcha 4

: > ~/sbx/mcp.log                                  # clear so the tool-fire check is unambiguous
CLAUDE_CONFIG_DIR=$HOME/.claude-work \
  claude -p "Use the MANNA MCP tools to resolve M51. Call the tool; do not guess." \
  --allowedTools "mcp__manna__vo_target_resolve"
grep -c "CallToolRequest" ~/sbx/mcp.log            # ≥1 = tool actually fired
```

> **VALIDATED 2026-07-01.** Returned M51 = **RA 202.469575° / Dec +47.19525833° (ICRS)**
> — driven by the local Qwen3.5-122B-A10B on vLLM, via the no-proxy Anthropic endpoint,
> via the persona, calling `vo_target_resolve`. The `⚠ claude.ai connectors are
> disabled…` line is benign (it just means the env auth/base-URL is in use → routing to
> vLLM). Note: `<think>` currently leaks into the reply text — cosmetic, see Gotcha 5.

---

## Gotchas & lessons learned

1. **containerd image store, not `/var/lib/docker`.** `Storage Driver: overlayfs` →
   image layers live in `/var/lib/containerd`. Sizing/pull failures: check
   `df -h /var/lib/containerd`.
2. **Use a scoped tool allowlist, never `--dangerously-skip-permissions`.**
   `--allowedTools "mcp__<server>__<tool>"` grants exactly that tool and denies
   everything else (no filesystem/bash), with no interactive prompts in `-p` mode.
3. **`claude mcp add --scope user`.** The default `local`/project scope only loads when
   `claude` runs from that project dir; `-p` from `~` saw *no* servers and the model
   reported "no MANNA tools". User scope loads everywhere.
4. **Token budget — THREE failure modes, all surface as a bogus "You're not
   authenticated with Claude" in chat** (Claude Code mis-maps the vLLM **HTTP 500** to an
   auth error — the `ANTHROPIC_API_KEY=dummy` trick only hides the *intermittent* login
   check, not a real 500). The arithmetic vLLM enforces is `input + max_output ≤
   --max-model-len`; blow it and every retry re-sends the same oversized prompt → three
   identical 500s.
   - **(a) Output request too big.** Claude Code requests up to `32000` output tokens by
     default; cap it with `CLAUDE_CODE_MAX_OUTPUT_TOKENS` (8192).
   - **(b) Input floor.** ~24.5K tokens before any conversation (system prompt + the 12
     `vo_*` tool schemas).
   - **(c) Tool results accumulate.** THE one that bit us (2026-07-02): a long agent loop
     stacked several `vo_tap_query` results and hit `57345 input + 8192 output = 65537`,
     one token over a 65536 window. **Two independent fixes, both now in place:**
     - **Bigger window** — raise `--max-model-len` (see Part 2; 131072 if the checkpoint's
       `max_position_embeddings` allows). The Blackwell box has ample KV headroom.
     - **Smaller tool results** — the MCP server never inlines large tabular results.
       Past `MANNA_INLINE_ROW_LIMIT` (default **200 rows**) / `MANNA_INLINE_BYTE_LIMIT`
       (default **48 KB**), a TAP result is routed to an async job and `vo_tap_results`
       hands back a `job_url` + pyvo `fetch_recipe` (the client fetches the data itself);
       cone/SIA results truncate inline with a `truncated` flag. These defaults are sized
       for a 64K backend; a single inline result can no longer overflow the window. Raise
       them for large-context models.
   - **(d) Long chat overflows the window (recurred 2026-07-23 at ~123K in).** Even with a
     131072 window, a long session's history eventually exceeds it. Root cause: behind
     `ANTHROPIC_BASE_URL`, Claude Code can't detect the model's real window (assumes ~200K),
     so its **auto-compaction never fires** before the true 131072 wall. **Fix — tell Claude
     Code the truth and make it compact early** (persona env, forwarded by
     `deploy/frontend/jupyterhub_config.py`; see `.env.example`):
     `CLAUDE_CODE_MAX_CONTEXT_TOKENS=131072` (applies directly for the unrecognized Qwen model
     name), `CLAUDE_CODE_AUTO_COMPACT_WINDOW=120000` + `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=85`
     (compact at ~102K, ~29K margin), and lower `CLAUDE_CODE_MAX_OUTPUT_TOKENS` to `4096`.
     Auto-compaction is a core agent-loop feature (emits `compact_boundary` in the stream), so
     it runs in the ACP persona session — a long chat then **auto-summarizes and continues in
     the same conversation** instead of 500-ing. Verify with `claude` + `/context` under the
     same env, or drive a long frontend session and watch for a compaction instead of the error.
5. **The Qwen3 `<think>` leak, and how it's actually fixed (root-caused 2026-07-23).**
   Symptom: the persona's replies begin with raw reasoning ("User greeted me, so I should…"
   / a trailing `</think>`). **Root cause** (found by capturing the persona's real request):
   **Claude Code sends `output_config: {effort: high}` on every request**, and vLLM honours
   any `effort` level (high/medium/low all trigger it; `minimal`/`none` are 400s) as "reason
   hard" — which **overrides** a server-side thinking-off default. Because we historically ran
   *without* `--reasoning-parser`, that reasoning spilled into the reply `content`.

   Old lore (now retired): the fear was that `--reasoning-parser qwen3` + `--tool-call-parser
   qwen3_coder` drops a `<tool_call>` emitted inside `<think>` (vLLM #39056), so we omitted the
   reasoning parser. **On vLLM 0.23.0 that bug does NOT reproduce** — tested `effort=high` with
   a tool and the model still emitted `tool_use` (`vo_target_resolve({target:"M51"})`,
   `stop_reason=tool_use`). So the parser is safe here.

   **FIX = one serve flag in `dlai01-vllm/docker-compose.yml`: `--reasoning-parser=qwen3`.**
   It routes the effort-triggered reasoning into a separate `thinking` block so it never enters
   the reply `content`. The model still reasons (so tool-use/ADQL **quality is unchanged**);
   only the visible output is cleaned. A normal reply comes back as `['thinking','text']` → real
   answer after the hidden reasoning.

   We deliberately do **not** add a `--default-chat-template-kwargs '{"enable_thinking": false}'`
   default. `effort` overrides it for the persona (so it wouldn't help there), and its only real
   effect would be turning thinking **off** for non-`effort` clients — notably the `evals/`
   harness — which would silently skew eval scores vs. old thinking-on baselines. The reasoning
   parser alone is the fix, and it keeps every path (persona + evals) reasoning as before.

   Confirm on dlai01: watch startup for both flags accepted (config line shows
   `reasoning_parser='qwen3'`), then chat via the frontend — reply is clean and a tool query
   (e.g. "resolve M51") still returns coords. If an older cached image rejects a flag,
   `docker compose pull` first.
6. **FP8 KV cache left OFF for now.** `--kv-cache-dtype fp8` roughly halves KV memory
   (a big concurrency lever) but is unvalidated on sm_120 here, and reportedly produced
   garbled output for another model on this GPU — validate before enabling.

## Scaling GPU count (freeing a Blackwell for other work)

**You cannot just drop `--tensor-parallel-size` to 3.** Qwen3.5-122B-A10B-FP8 has **32
attention heads**, and vLLM enforces `num_attention_heads % TP == 0` → TP must be 1, 2,
or 4. `TP=3` aborts at startup (`heads must be divisible by tensor parallel size`), and
with `restart: unless-stopped` the container then crash-loops and 502s the endpoint.

To use exactly **3 of the 4 GPUs**, use **pipeline parallelism** instead (validated
2026-07-21): in `dlai01-vllm/docker-compose.yml`, replace `--tensor-parallel-size=4`
with `--pipeline-parallel-size=3 --tensor-parallel-size=1` (48 hidden layers / 3 = 16
per GPU, clean), and pin the container to specific GPUs so one stays idle:
`device_ids: ['0','1','2']` (replacing `count: all`). Trade-off: PP favors concurrent
throughput over single-request latency. Alternative if you'd rather keep tensor
parallelism: `TP=2` (frees **two** GPUs, tighter KV headroom).

**Swap procedure (the running container is a bare `docker run`, not this compose
project, so compose won't adopt it — you must remove it first):**

```bash
# snapshot the old args for rollback, then swap
docker inspect vllm --format '{{json .Args}}'      # record the TP=4 command
docker rm -f vllm                                  # brief downtime starts here
cd deploy/dlai01-vllm && docker compose up -d && docker compose logs -f
# ✅ look for "Application startup complete" + Worker_PP0/PP1/PP2 (world_size=3)
# confirm: nvidia-smi shows the pinned-out GPU at 0 MiB / 0%
```

Revert = restore `--tensor-parallel-size=4` / `count: all` and recreate.

## Current status & next steps

**Done:** local model (Qwen3.5-122B-A10B) hosted on dlai01 and consumed by the persona
+ MCP, end to end. All on loopback / inside dlai01.

**Done (2026-07-02) — vLLM exposed off-box, validated from a laptop AND from the
dockerized frontend.** The topology differs from the plan below: instead of a
self-hosted TLS proxy on `dlai01.csdc.noirlab.edu:443` with a `vllm --api-key` bearer,
**Chadd stood up an nginx proxy** that terminates TLS + HTTP Basic auth and forwards to
vLLM:

```
laptop / frontend container ──HTTPS+Basic──► https://datalab.noirlab.edu/astro-archives-mcp
                                             └─ nginx (TLS, Basic auth) ─► dlai01:8002 ─► vLLM (keyless)
```

- vLLM is relaunched with **`-p 8002:8000`** (0.0.0.0 bind, not loopback) so the off-box
  nginx can reach it. It runs **keyless** — nginx does the auth.
- **Client config (bare curl / laptop):** send `Authorization: Basic <base64 user:pass>`
  (creds DM'd by Chadd). A 200 + `{"type":"message",…}` envelope = the full chain works.
- **Claude Code / persona config — the load-bearing gotcha:** carry the Basic credential
  in **`ANTHROPIC_CUSTOM_HEADERS`**, and **do NOT set `ANTHROPIC_AUTH_TOKEN`**. Setting
  the token makes Claude Code send a competing `Authorization: Bearer` header → nginx
  401 (even though bare curl with only the Basic header returns 200). Confirmed inside
  `frontend-lab-1`: with AUTH_TOKEN set → 401; unset → the persona resolves M51 via the
  MCP tool through vLLM.
- **Also set `ANTHROPIC_API_KEY=dummy`** (rides `x-api-key`, a different header — no
  collision with the Basic `Authorization`, and the keyless vLLM ignores it). Without a
  credential Claude Code natively recognizes, it intermittently declares *"You're not
  authenticated / run claude /login"* mid-session even though the CUSTOM_HEADERS Basic auth
  is working. The dummy key keeps Claude Code's login-state check satisfied.
- ⚠️ **Note the path name:** the proxy path is `/astro-archives-mcp` — NOIRLab's nginx
  block, named after this project's former name. It fronts the **LLM**, not the MCP
  server. It does not change when this repo is renamed; ask Chadd if it should be
  re-pointed to `/manna`.

**Done (2026-07-02) — dockerized frontend validated against this backend.** The
`deploy/frontend/` stack (MCP + Jupyter AI persona), **chat mode**, reaches the proxy and
resolves M51 end-to-end. Config lives in `deploy/frontend/.env(.example)`. Because the
proxy is public TLS, the exact same `.env` works from a Data Lab server unchanged.

**Done (2026-07-02) — context-overflow fix.** A `vo_tap_query`-heavy agent loop overflowed
the 65536 window (`57345 + 8192 = 65537`), surfacing as a spurious "You're not authenticated
with Claude" (Gotcha 4c). Fixed on both sides: `--max-model-len` raised to 131072, and the
MCP server now routes large TAP results to an async job and hands back a `result_url` +
pyvo `fetch_recipe` (the client fetches the bytes itself), at much lower inline caps
(`MANNA_INLINE_ROW_LIMIT=200`, `MANNA_INLINE_BYTE_LIMIT=48 KB`).

**Done (2026-07-07) — persistence.** vLLM is now a durable compose service
(`dlai01-vllm/docker-compose.yml`, `restart: unless-stopped`) instead of a bare
`docker run`, so it comes back after dlai01's periodic reboots:
`cd deploy/dlai01-vllm && docker compose up -d`. Model / context-length / api-key are
overridable via env (`VLLM_MODEL`, `VLLM_MAX_MODEL_LEN`, `VLLM_API_KEY`).

**Next (not yet started):**
- **Harden the exposed endpoint.** vLLM binds `0.0.0.0:8002` **keyless** — anything
  that can reach `dlai01:8002` directly bypasses nginx's Basic auth. Confirm with Randy
  that the firewall restricts 8002 to the proxy host only; if it's broader, set
  `VLLM_API_KEY` (uncomment the `--api-key` line in the compose) and have Chadd inject it
  upstream.
- **`hub` mode against vLLM** — re-validate JupyterHub + DockerSpawner with the same `.env`.
- ~~**Thinking-off** cleanup (Gotcha 5) for clean chat UX.~~ **DONE (2026-07-23):**
  `--reasoning-parser=qwen3` in the compose routes the effort-triggered reasoning into a separate
  block instead of leaking it into the reply. Deploy on dlai01 (`docker compose up -d`); confirmed
  the preamble is gone and tool calls still fire in the frontend chat. See Gotcha 5 for the root cause.
- **Concurrency load test** at agentic context lengths (KV cache is the limiter;
  prefix-caching the ~24.5K static tool-schema prefix is the big lever) to size gp12.

## Quick reproduce (all-in-one)

```bash
# 1. MCP server (rootless, loopback)
cd ~/sbx/astro-archives-mcp && export PATH="$HOME/.local/bin:$PATH" XDG_CACHE_HOME="$HOME/.cache"
nohup env MANNA_PORT=8000 uv run python -m manna > ~/sbx/mcp.log 2>&1 &
CLAUDE_CONFIG_DIR=$HOME/.claude-work claude mcp add --scope user --transport http manna http://127.0.0.1:8000/mcp/

# 2. Model on vLLM (TP=4)
docker rm -f vllm 2>/dev/null
docker run -d --name vllm --gpus all --ipc=host \
  -v /mlhome/dgause/hf:/root/.cache/huggingface -p 127.0.0.1:8001:8000 \
  vllm/vllm-openai:latest --model Qwen/Qwen3.5-122B-A10B-FP8 \
  --tensor-parallel-size 4 --enable-auto-tool-choice --tool-call-parser qwen3_coder --max-model-len 131072

# 3. Persona → local model, validate
export ANTHROPIC_BASE_URL=http://127.0.0.1:8001 ANTHROPIC_AUTH_TOKEN=dummy CLAUDE_CODE_MAX_OUTPUT_TOKENS=8192
export ANTHROPIC_DEFAULT_OPUS_MODEL=Qwen/Qwen3.5-122B-A10B-FP8 \
       ANTHROPIC_DEFAULT_SONNET_MODEL=Qwen/Qwen3.5-122B-A10B-FP8 \
       ANTHROPIC_DEFAULT_HAIKU_MODEL=Qwen/Qwen3.5-122B-A10B-FP8
CLAUDE_CONFIG_DIR=$HOME/.claude-work claude -p \
  "Use the MANNA MCP tools to resolve M51. Call the tool; do not guess." \
  --allowedTools "mcp__manna__vo_target_resolve"
```
