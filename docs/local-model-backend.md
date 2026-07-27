# Local-model backend for the Jupyter AI persona (dlai01)

Status: **research draft — validate on the box before relying on it.** This explores
backing the Jupyter AI "Claude" persona with a self-hosted model on the GPU box
`dlai01` (4× NVIDIA RTX PRO 6000 Blackwell, ~96 GB each ≈ 384 GB, sm_120, CUDA 13.x)
instead of hosted Claude. It's the §4 "local model" option in `deploy/gp13-runbook.md`.
Goal framing: **PoC feasibility, optimized for agentic MCP tool-calling reliability.**
Throughput/concurrency was out of the original PoC scope but matters for gp13's dozens of
users — covered in **§5**.

> **Confidence note.** Backed by a deep-research pass (25 sources). Across two
> verification runs, **13 claims cleared full multi-vote adversarial verification**; the
> rest abstained when the runs hit session limits (they are *unverified*, not refuted).
> Items are tagged **[verified]** (multi-vote 3-0) or **[lead]** (single-source,
> plausible, unverified). Re-verify [lead] items — especially exact version pins and 2026
> model names — on dlai01. Verification flagged two corrections vs. an earlier draft:
> llama.cpp is **not** a clean fallback here (§2), and the recommended Qwen3 parser combo
> has a **verified tool-loss footgun** (§4).

## Why this is even tractable: the persona inherits env

The persona launches `claude-agent-acp`, which wraps Claude Code, which reads
`ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` from its environment. Same inheritance
trick we used for `CLAUDE_CONFIG_DIR` (work account): set these in the JupyterLab
launch env and the persona talks to the local model. The MCP path is unchanged — the
`vo_*` tools work identically regardless of which model backs the persona.

## 1. Bridge: prefer vLLM's native Anthropic endpoint

- **[verified] vLLM natively implements the Anthropic Messages API** (`/v1/messages`),
  the same API Claude Code speaks — so Claude Code points *straight at vLLM*, with **no
  separate translation proxy**. This is the cleanest path and removes the
  Anthropic↔OpenAI translation layer that is the main source of tool-call breakage.
  Source: vLLM docs, Claude Code integration.
- **[verified] Env to point Claude Code at vLLM:** `ANTHROPIC_BASE_URL=http://dlai01:8000`,
  `ANTHROPIC_AUTH_TOKEN=dummy` (any value), and map tiers with
  `ANTHROPIC_DEFAULT_OPUS_MODEL` / `_SONNET_MODEL` / `_HAIKU_MODEL` = your served model
  name.
- **[verified] Fallback bridges** if the native path misbehaves: `claude-code-router`
  (musistudio, local gateway at `http://127.0.0.1:3456`) or a **LiteLLM** proxy. LiteLLM
  is verified to bridge Claude Code → arbitrary backends: set `ANTHROPIC_BASE_URL` to the
  proxy and `ANTHROPIC_AUTH_TOKEN` to the LiteLLM master key, with models declared in a
  `config.yaml` `model_list`.

## 2. Serving on Blackwell (sm_120, CUDA 13) — the riskiest part

- **[verified] All three engines (vLLM, TensorRT-LLM, llama.cpp) have been empirically
  validated on the RTX PRO 6000 96 GB (sm_120) Blackwell GPU** (blackwell-llm-toolkit,
  as of 2026-05-11). So serving on this hardware is a solved problem *with the right
  recipe* — but the recipe is exact and version-sensitive.
- **[verified] llama.cpp is NOT a drop-in fallback here.** Its CUDA build **fails** on
  sm_120 with CUDA Toolkit 13.1.115 — MXFP4 PTX instructions (`mma with block scale`,
  `.kind::mxf4`, `.block_scale`) are unsupported on `.target sm_120`, and the issue was
  **open/unresolved as of Feb 2026** (llama.cpp #19662). A working build exists (per the
  toolkit above) but you must use a validated recipe / avoid the MXFP4 path — do not
  assume `make`-and-go.
- **[lead] vLLM install is finicky but documented.** Reported working stacks pair a
  recent/nightly vLLM with `torch …+cu130` and matched FlashInfer/Triton (e.g. PyTorch
  `2.10.0+cu130`, vLLM ~`0.17.x`, FlashInfer `0.6.4`, Triton `3.6.0`), and need the
  **full system CUDA 13 toolkit** (not just PyPI wheel fragments) for FlashInfer JIT.
- **Action:** start from the blackwell-llm-toolkit recipe rather than a fresh install;
  budget real time here; pin and record the exact working versions.

## 3. Model choice (tool-use reliability)

- **[verified] Judge models by BFCL V4** (holistic agentic tool-use), and/or Tau2-bench.
Two candidates, and an honest tradeoff between them:

- **[lead] GLM family — the tool-use-quality leader.** GLM tops the agentic tool-use
  benchmarks the research surfaced (GLM-4.5 ≈ 70.9% BFCL V4 open-weight lead; GLM-4.7/5.x
  very high on Tau2-Telecom). By the stated priority (tool-use reliability) this is the
  model to actually try to land. Caveat: **not** verified on this exact Blackwell setup,
  so expect to do the serving bring-up yourself.
- **[lead] Qwen3 — the proven-on-this-hardware pick.** Qwen3-235B-A22B (235B total /
  **22B active** MoE) is the family specifically validated on RTX PRO 6000 sm_120 with a
  known vLLM parser, and the low active-param count helps decode throughput (see §5).
  Slightly below GLM on tool-use benchmarks.
- **[lead] Kimi K2.x — skip on this box.** Cited for tool-call stability, but it's a
  ~1T-param MoE; at 384 GB it needs aggressive quantization that hurts quality. Poor fit
  *for this hardware*.

**PoC recommendation (explicit tradeoff):**
- **Bring the pipeline up first on Qwen3-235B-A22B** — lowest yak-shaving (validated
  Blackwell + parser path), proves the persona→MCP loop end-to-end.
- **Then A/B against GLM-4.6**, which is the better bet *if tool-use reliability is the
  hard requirement* — accept that you'll do its serving setup from scratch.
- **Smaller fallback:** a ~30B Qwen3 (single GPU) for the very first bring-up — and note
  (§5) a ~70B-class model may actually serve *more concurrent users* than the 235B.

## 4. Integration failure modes & mitigations

- **[verified] Parser/template mismatch** → tool calls silently dropped. Use the parser
  matched to the family: Qwen → `hermes`/`qwen3_coder`, DeepSeek-V3 → `deepseek_v3`,
  Llama 3.x → `llama3_json`, Mistral → `mistral`. Always pair with the matching chat
  template.
- **[verified] Reasoning-parser eats the tool call (the Qwen3 footgun).** For Qwen3-MoE
  models, vLLM's reasoning parser pulls everything before `</think>` into the *reasoning*
  field, and the tool-call parser only inspects *content* — so a `<tool_call>` block
  emitted inside `<think>` **never reaches the tool parser and the call is silently lost**
  (vLLM #39056). This happens **specifically with the `qwen3_reasoning_parser` +
  `qwen3_coder` combo** — i.e. exactly the flags in the recommended stack below.
  Mitigate: **disable thinking for the PoC** (sidesteps it entirely), or track vLLM #39056
  for the fix; verify tool calls actually land before trusting the setup.
- **[lead] Thinking-token budget exhaustion.** Reasoning models can also spend the whole
  `max_tokens` inside `<think>` → `content:null` / `finish_reason:length`, a silent
  HTTP-200 that stalls the agent loop. Mitigate: generous `max_tokens`, or thinking off.
- **[lead] Streaming tool-call bugs** in some vLLM versions (raw XML in `content` instead
  of structured `tool_calls`, `finish_reason: stop`). Test your version; non-streaming is
  safer to start.
- **[lead] `tool_choice:auto` may not guarantee schema-valid JSON** (a verifier pushed
  back on the strict-mode specifics, so treat as unconfirmed). Regardless, expect
  occasional malformed args; the agent loop should tolerate/retry.

## 5. Concurrency — supporting dozens of gp13 users

The PoC research was deliberately scoped to single-user feasibility. gp13 must serve
**dozens of concurrent users**, which materially changes the calculus. (Sources: VRLA
Tech RTX PRO 6000 capacity analysis, allenkuo Blackwell-vLLM benchmarks, vLLM
optimization docs, Spheron KV-cache guide — all [lead].)

- **Hosted Claude (v1) sidesteps this entirely.** Each user's persona is an independent
  Claude Code process hitting Anthropic's API — dozens of users = dozens of independent
  clients, no shared serving bottleneck (only rate limits / cost). **This is a strong
  argument for hosted Claude as the multi-user v1.**
- **For a local model, KV cache — not compute — is the concurrency limiter.** vLLM uses
  continuous batching + PagedAttention; concurrent capacity ≈ (VRAM left after weights) ÷
  (KV cache per active request). Reported single-GPU numbers: a 70B FP8 model leaves
  ~26 GB for KV → ~13–26 concurrent users **at 4K context**. On the 4×96 GB box (384 GB),
  70B at FP16 leaves ~244 GB → **50–100+ concurrent at 4K**.
- **Agentic contexts blow up those numbers.** Those figures assume 4K tokens; agent loops
  accumulate context (MCP tool schemas + multi-turn → 15–32K+ tokens), and KV cache grows
  linearly with length. At 32K context, per-request KV is ~8× larger, cutting concurrency
  roughly proportionally. Plan for far fewer concurrent agents than the 4K headline.
- **Model size vs. concurrency is a direct tension.** Qwen3-235B-A22B in FP8 (~235 GB
  weights) leaves only ~150 GB for KV across the whole batch — so the *bigger, better*
  model supports *fewer* concurrent long-context agents. A **70B-class model leaves far
  more KV headroom**, so for multi-user it may beat the 235B despite lower tool-use
  scores. MoE's 22B active params help *decode speed/throughput*, not KV footprint.
- **Levers that buy concurrency:** **FP8 KV cache** (~halves KV footprint); **prefix
  caching** (big win here — every persona sends the *same* `vo_*` tool-schema prefix, so
  it's shared across requests, saving KV + prefill); `--max-num-seqs` / `--gpu-memory-
  utilization 0.9`; CPU `--swap-space`; and horizontally, **multiple vLLM replicas** behind
  a load balancer once one instance saturates.
- **Throughput reality on this hardware:** ~89 tok/s single-stream decode, ~342 tok/s
  aggregate at 4 parallel requests, ~20K tok/s prefill. For agents, TTFT/prefill dominates
  perceived latency (each step re-prefills the growing context), so prefill speed and
  prefix caching matter more than raw decode.

**Bottom line:** dozens of concurrent users is comfortable with **hosted Claude**;
achievable for a local model only with **capacity planning** (likely a ~70B-class model,
FP8 KV cache, prefix caching, capped context, and/or replicas) — not with the
tool-use-max 235B at long contexts without compromise. A real load test on dlai01 is the
only way to fix the numbers.

## Recommended PoC stack

| Layer | Choice | Key flags / env |
|---|---|---|
| Serving | **vLLM** from a validated Blackwell recipe (blackwell-llm-toolkit), tensor-parallel. llama.cpp only via a validated build (CUDA build breaks by default — §2) | `--tensor-parallel-size 4 --enable-auto-tool-choice --tool-call-parser qwen3_coder --reasoning-parser qwen3 --served-model-name local-claude` **+ disable thinking** (avoids the #39056 tool-loss footgun, §4) |
| Bridge | **vLLM native Anthropic endpoint** (no proxy); CCR/LiteLLM verified fallbacks | — |
| Model | **Qwen3-235B-A22B** (primary) / ~30B Qwen3 (fallback) / GLM-4.6 (if tool-use weak). `gpt-oss-120b` + `--tool-call-parser openai` is vLLM's own documented known-good combo | — |
| Concurrency (§5) | FP8 KV cache + prefix caching are the big levers; cap context; replicas to scale out | `--kv-cache-dtype fp8 --enable-prefix-caching --max-num-seqs <tuned> --gpu-memory-utilization 0.9 --max-model-len <capped>` |
| Harness | JupyterLab launch env (inherited by the persona) | `ANTHROPIC_BASE_URL=http://dlai01:8000` `ANTHROPIC_AUTH_TOKEN=dummy` `ANTHROPIC_DEFAULT_OPUS_MODEL=local-claude` (+ SONNET/HAIKU) |

**Top risks to watch:** (1) Blackwell+CUDA-13 install friction (start from a validated
recipe; llama.cpp's default CUDA build is broken on sm_120); (2) the `qwen3_coder` +
`qwen3` reasoning-parser tool-loss bug (disable thinking, verify calls land); (3)
thinking-token budget exhaustion stalling the agent loop; (4) version-specific streaming
tool-call bugs; (5) **concurrency at gp13 scale** — KV cache, not compute, is the limiter
for long agentic contexts; the tool-use-max 235B trades away concurrency headroom (§5).

## Sources
vLLM Claude Code integration & tool-calling docs (primary); BFCL V4 leaderboard
(gorilla.cs.berkeley.edu); claude-code-router (github.com/musistudio); lastloop-ai
vllm-blackwell-guide; vLLM issues #37714 / #31871 / #32713; stevescargall.com thinking-mode
analysis; dev.to dcruver Claude-Code-via-vLLM-and-LiteLLM. Concurrency (§5): VRLA Tech
RTX PRO 6000 capacity analysis; allenkuo Blackwell vLLM-vs-Ollama agent benchmarks; vLLM
optimization & tool-calling docs; Spheron KV-cache optimization guide. Full list in the
research run output (`tasks/wqv4strey.output`).
