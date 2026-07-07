# dlai01 Model-Hosting — Validation Record & Runbook

**What this documents:** hosting an open-weight LLM (Qwen3.5) on the dlai01 GPU box
via vLLM, and consuming it from a Claude Code persona that calls the astro-archives
**MCP** tool server — the full local-model chain, proven end to end. Exact working
commands, verified results, and every gotcha we hit.

Paired with `docs/local-model-backend.md` (the *why* behind model choice) and
`docs/jupyter-ai-integration.md` (the persona/MCP architecture). Status: **local chain
VALIDATED** and **exposed off-box via the datalab nginx proxy (2026-07-02)** — reachable
from a laptop and from the dockerized frontend (see *Current status* at the end).

---

## Architecture

Two hosts, split backend/frontend:

- **dlai01** — the **backend / model host**: 4× RTX PRO 6000 Blackwell, runs vLLM
  serving the LLM. Where the GPUs and docker access live.
- **gp13** — the production **frontend**: a shared JupyterHub running Jupyter AI + the
  Claude Code persona per user. (Not yet accessible; the MCP server + a JupyterHub are
  being stood up locally first as a gp13 stand-in.)

The chain, and the two independent connections the persona makes:

```
JupyterLab (Jupyter AI v3)
      │
      ▼
 ACP persona = Claude Code ──(model)──► vLLM  [ANTHROPIC_BASE_URL]      ← dlai01
      │
      └─────────────────────(tools)──► astro-archives MCP  [/mcp/]      ← colocated
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
cd ~/sbx/astro-archives-mcp
export PATH="$HOME/.local/bin:$PATH" XDG_CACHE_HOME="$HOME/.cache"   # writable astropy/tmp cache
nohup env STABLE_PORT=8000 uv run python -m astro_archives_mcp > ~/sbx/mcp.log 2>&1 &
curl -fsS http://127.0.0.1:8000/health        # {"status":"ok","version":"0.3.0",...}
```

Register it with Claude Code — **user scope is required** (see Gotcha 3):

```bash
CLAUDE_CONFIG_DIR=$HOME/.claude-work \
  claude mcp add --scope user --transport http astro-archives http://127.0.0.1:8000/mcp/
CLAUDE_CONFIG_DIR=$HOME/.claude-work claude mcp list       # astro-archives: ✓ Connected
```

## Part 2 — hosting the model on vLLM

**Model: `Qwen/Qwen3.5-122B-A10B-FP8`** (122B total / ~10B active MoE). Chosen via a
fact-checked model survey (`docs/local-model-backend.md`): near-top open-weight BFCL V4
(~0.722), fits FP8 (~122 GB) with large KV-cache headroom, MoE decode is fast and
concurrency-friendly. Tool-call parser: `qwen3_coder`. Runner-up to A/B later:
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
- **`--reasoning-parser` is deliberately omitted** — see Gotcha 5.

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
  claude -p "Use the astro-archives MCP tools to resolve M51. Call the tool; do not guess." \
  --allowedTools "mcp__astro-archives__vo_target_resolve"
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
   reported "no astro-archives tools". User scope loads everywhere.
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
     - **Smaller tool results** — the MCP server spills tabular results to the Parquet
       Resource tier (a tiny `resource_uri` + 50-row preview) past `STABLE_INLINE_ROW_LIMIT`
       (default **200 rows**) / `STABLE_INLINE_BYTE_LIMIT` (default **48 KB**). These
       defaults are sized for a 64K backend; a single inline result can no longer overflow
       the window. Raise them for large-context models.
5. **The Qwen3 `<think>` tool-loss footgun (vLLM #39056) — and the mitigation we use.**
   With `--reasoning-parser qwen3` + `--tool-call-parser qwen3_coder`, a `<tool_call>`
   emitted inside `<think>` is pulled into the *reasoning* field and never reaches the
   tool parser → **silently dropped**. This is the real basis of the "Qwen3.5 is bad at
   tools" rumor (the model is actually top of open-weight BFCL). **Mitigation: omit
   `--reasoning-parser`** — the call stays in `content` where `qwen3_coder` finds it.
   Verified working (thinking stays on, tool still fires). **Side effect:** raw
   `<think>…</think>` text leaks into the reply. Cosmetic; deferred to gp13-deployment
   cleanup. The clean fix is a request-level `chat_template_kwargs:{enable_thinking:
   false}`, which Claude Code doesn't expose — so it'll need a thin proxy that injects
   it, a custom chat template baked into the served model, or a non-thinking checkpoint.
   (`vllm serve --help` crashes in this build, so there's no easy serve-flag route.)
6. **FP8 KV cache left OFF for now.** `--kv-cache-dtype fp8` roughly halves KV memory
   (a big concurrency lever) but is unvalidated on sm_120 here, and reportedly produced
   garbled output for another model on this GPU — validate before enabling.

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
- ⚠️ **Note the path name:** the proxy path is `/astro-archives-mcp` but it fronts the
  **LLM**, not the MCP server (a naming coincidence). Worth asking Chadd to rename.

**Done (2026-07-02) — dockerized frontend validated against this backend.** The
`deploy/frontend/` stack (MCP + Jupyter AI persona), **chat mode**, reaches the proxy and
resolves M51 end-to-end. Config lives in `deploy/frontend/.env(.example)`. Because the
proxy is public TLS, the exact same `.env` works from a Data Lab server unchanged.

**Done (2026-07-02) — context-overflow fix.** A `vo_tap_query`-heavy agent loop overflowed
the 65536 window (`57345 + 8192 = 65537`), surfacing as a spurious "You're not authenticated
with Claude" (Gotcha 4c). Fixed on both sides: `--max-model-len` raised to 131072, and the
MCP server now spills large tabular results to the Parquet Resource tier at much lower inline
caps (`STABLE_INLINE_ROW_LIMIT=200`, `STABLE_INLINE_BYTE_LIMIT=48 KB`).

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
- **Thinking-off** cleanup (Gotcha 5) for clean chat UX.
- **Concurrency load test** at agentic context lengths (KV cache is the limiter;
  prefix-caching the ~24.5K static tool-schema prefix is the big lever) to size gp13.

## Quick reproduce (all-in-one)

```bash
# 1. MCP server (rootless, loopback)
cd ~/sbx/astro-archives-mcp && export PATH="$HOME/.local/bin:$PATH" XDG_CACHE_HOME="$HOME/.cache"
nohup env STABLE_PORT=8000 uv run python -m astro_archives_mcp > ~/sbx/mcp.log 2>&1 &
CLAUDE_CONFIG_DIR=$HOME/.claude-work claude mcp add --scope user --transport http astro-archives http://127.0.0.1:8000/mcp/

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
  "Use the astro-archives MCP tools to resolve M51. Call the tool; do not guess." \
  --allowedTools "mcp__astro-archives__vo_target_resolve"
```
