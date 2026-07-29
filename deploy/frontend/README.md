# Frontend stack (dockerized) — MCP + Jupyter AI persona

The **frontend** half of the system: the MANNA **MCP tool server** plus a
**Jupyter AI persona** (Claude Code), containerized and runnable in two modes. The
**model** lives elsewhere (dlai01 vLLM, reached over the network) — see
`../dlai01-vllm-runbook.md`. Architecture recap:

```
[ this stack: MCP + persona + Jupyter ]  ──(model, ANTHROPIC_BASE_URL)──►  dlai01 vLLM
        run locally now, lifts to gp12                                     (443, once open)
```

## Modes

| Mode | What runs | URL | Use when |
|------|-----------|-----|----------|
| **chat** | `mcp` + one JupyterLab (Jupyter AI chat panel) | http://localhost:8888 | You just want to chat with model+persona+tools. No Hub. |
| **hub**  | `mcp` + JupyterHub (DockerSpawner → one frontend container per user) | http://localhost:8081 | Multi-user; the gp12 mirror. |

The `mcp` service runs in both modes; pick exactly one of `chat`/`hub`.

## Quick start

```bash
cp .env.example .env          # set the model endpoint + token (or leave blank for hosted Claude)

# chat mode
docker compose --profile chat up --build
# → open http://localhost:8888, open the Jupyter AI chat, @-mention @CosmicCoder

# hub mode
docker compose build lab      # build the single-user image DockerSpawner launches
docker compose --profile hub up --build
# → open http://localhost:8081, log in (dummy auth, JUPYTERHUB_DUMMY_PASSWORD)
```

## Configuration (`.env`)

- **Model backend:** depends on where you are relative to the Astro Data Lab network.
  - *Off-network* (laptop, CI): `ANTHROPIC_BASE_URL` at the **datalab nginx proxy**
    (`https://datalab.noirlab.edu/astro-archives-mcp`), Basic-auth credential in
    `ANTHROPIC_CUSTOM_HEADERS` (`Authorization: Basic <base64>`). **Do NOT set
    `ANTHROPIC_AUTH_TOKEN`** — it injects a `Bearer` header that collides with the
    Basic header and nginx 401s (see `.env.example`).
  - *On the ADL network* (gp12): point straight at vLLM,
    `http://dlai01.csdc.noirlab.edu:8002` — no proxy, no Basic auth, and so no header
    collision. See `../gp12-runbook.md`.
  - Either way `ANTHROPIC_API_KEY=dummy` is required (Claude Code's own login-state
    check). Leave `ANTHROPIC_BASE_URL` blank to fall back to **hosted Claude**.
- `ANTHROPIC_DEFAULT_*_MODEL` must match vLLM's served model name (local backend
  only; comment out for hosted Claude).
- `CLAUDE_CODE_MAX_OUTPUT_TOKENS` caps output to fit the served window (runbook Gotcha 4).
- Hub mode: `JUPYTERHUB_DUMMY_PASSWORD`, and `DOCKER_NETWORK` must equal the compose
  network (`<project>_default`; default `frontend_default` — update if you run with a
  different `-p` project name).

## How it maps to the tools

- **MCP** is a shared service at `http://mcp:8000/mcp/` (see `mcp_settings.json`, baked
  into the frontend image at `~/.jupyter/`). One deployment serves every user
  container — the same topology gp12 uses (`../gp12-runbook.md`).
- **Persona** = `claude-agent-acp` wrapping the `claude` CLI; reads the model endpoint
  from the injected `ANTHROPIC_*` env. The image **rebrands it as `@CosmicCoder`**
  (CosmicAI) by patching the pinned persona's display name/avatar in place — behavior is
  unchanged. See "Renaming the persona" in `../../docs/jupyter-ai-integration.md` for why
  it's a patch and not config, and why `jupyter-ai`/`jupyter-ai-acp-client` are pinned.

## Lifting to gp12

Same images, same shared-MCP topology. ADL ops point their JupyterHub's single-user
image at this frontend image and inject the same `ANTHROPIC_*` env for the model plus
the MCP `mcp_settings.json`. The `chat` mode is a faithful stand-in for a single
spawned user session. What differs on gp12 — the dev defaults that must change, and
the open questions for ADL ops — is in `../gp12-runbook.md`.

## Status / caveats

- **`chat` mode VALIDATED end-to-end against the real vLLM** (2026-07-02, macOS arm64):
  `mcp` service healthy; the lab container reaches `http://mcp:8000` cross-container AND
  the `datalab.noirlab.edu` proxy (HTTP 200 with Basic auth); and an **in-container
  persona call resolved M51 via the MCP tool through vLLM** (persona → datalab proxy →
  the then-production local model (Qwen3.5-era; current model: gpt-oss-120b, re-validated
  2026-07-28) vLLM → `mcp:8000` → `vo_target_resolve` → RA 202.4696°, Dec +47.195°).
  Previously (2026-07-01) validated against hosted Claude.
- **Gotcha — Basic auth vs. `ANTHROPIC_AUTH_TOKEN`.** The proxy uses HTTP Basic auth
  carried in `ANTHROPIC_CUSTOM_HEADERS`. Setting `ANTHROPIC_AUTH_TOKEN` too makes Claude
  Code send a competing `Bearer` header → nginx 401. Leave AUTH_TOKEN unset. See
  `.env.example`.
- **Gotcha — set `ANTHROPIC_API_KEY=dummy` or you get logged out mid-session.** With auth
  living only in `CUSTOM_HEADERS`, Claude Code has no credential its own login-state check
  recognizes, so it intermittently prints *"You're not authenticated / run claude /login"*
  mid-session. A dummy `ANTHROPIC_API_KEY` rides `x-api-key` (separate header, no collision
  with Basic; keyless vLLM ignores it) and keeps Claude Code "logged in". Forwarded to
  spawned hub containers via `jupyterhub_config.py`.
- **Gotcha — `ANTHROPIC_DEFAULT_*_MODEL` is backend-coupled.** Set to vLLM's served name
  for the local backend; **comment out for hosted Claude** or Claude Code requests a
  "openai/…" model Anthropic doesn't have ("model may not exist"). See `.env.example`.
- **`<think>` leak — FIXED (2026-07-23).** The served model's replies used to begin with a
  reasoning preamble ending in `</think>`. Root cause: Claude Code sends `output_config.effort=high`,
  which makes vLLM reason; without a reasoning parser that reasoning leaked into the reply.
  Fixed at the model server with a model-matched `--reasoning-parser` serve flag; currently
  `openai_gptoss` for gpt-oss-120b — so the reasoning goes to a
  separate block, not the visible text — tool calls still fire and workflow quality is unchanged
  (runbook Gotcha 5 / `dlai01-vllm/docker-compose.yml`). Requires the dlai01 vLLM to be
  redeployed with that flag.
- **`hub` mode VALIDATED against vLLM** (2026-07-02): a hub-spawned single-user container
  inherited the forwarded `ANTHROPIC_*` env (incl. `ANTHROPIC_CUSTOM_HEADERS`, with
  `AUTH_TOKEN` unset) and its persona resolved M51 via the MCP tool through vLLM. Note:
  `jupyterhub_config.py` must forward `ANTHROPIC_CUSTOM_HEADERS` (added 2026-07-02) or the
  spawned persona has no Basic-auth header → 401. Watch the jupyterhub↔singleuser version
  match and the `DOCKER_NETWORK` name when porting.
- **Auth is dummy** in hub mode — local dev only. Replace the authenticator for anything
  exposed.
