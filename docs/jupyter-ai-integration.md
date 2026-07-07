# Integrating astro-archives-mcp with Jupyter AI

Status: working notes / local-test recipe. Target deployment: Astro Data Lab notebook
server **gp13**, surfacing the VO tools to notebook users via Jupyter AI chat.

## How the pieces fit

Jupyter AI **v3** (a rewrite — v2 was LangChain `%%ai` magics with no MCP) wires up
three layers:

```
JupyterLab chat  →  ACP agent ("persona")  →  MCP servers
  (jupyter-ai)        e.g. Claude Code           this server, over HTTP at /mcp/
                      (carries its own LLM creds)
```

- The **persona** is an [ACP](https://agentclientprotocol.com) agent (Claude Code,
  Gemini CLI, Codex, Goose, …). It is a separate process with its own model
  credentials — Jupyter AI ships with *no* agent by default.
- The persona is what actually *calls* MCP tools. Registering an MCP server only makes
  its tools available; you still need a working persona to invoke them.
- This server already exposes **Streamable HTTP** at `http://<host>:8000/mcp/`
  (FastMCP `http_app`), which is exactly what Jupyter AI's `"http"` server type expects.
  No server-side code changes are needed for a basic read-only integration.

> **Verified.** A real MCP handshake + `tools/list` against `http://localhost:8000/mcp/`
> enumerates all 12 `vo_*` tools. A bare `POST /mcp` (no slash) returns a 307 redirect to
> `/mcp/`, so always configure the trailing-slash URL.

## Prerequisites

| Component        | Install                                                        | Notes |
|------------------|----------------------------------------------------------------|-------|
| JupyterLab 4 + Jupyter AI v3 | `pip install jupyter-ai` (or conda-forge)          | Use a **separate env** from this server's `uv` env. |
| Node.js          | conda/system package                                           | Required by the Claude Code ACP adapter. |
| An ACP agent     | `npm install -g @anthropic-ai/claude-code @zed-industries/claude-agent-acp` | Provides the `claude-agent-acp` binary the Claude persona launches; it wraps the `claude` CLI for auth/model calls, so install both (verified against `jupyter_ai_acp_client` 0.1.5). npm warns the adapter was renamed to `@agentclientprotocol/claude-agent-acp` — either works today. |
| Agent auth       | reuse your existing Claude Code login                          | The Claude persona wraps the `claude` CLI's own auth, so if you already use Claude Code you're set. If a token is expired the persona replies telling you to run `claude /login`. No separate API key step. |
| This MCP server  | `uv run python -m astro_archives_mcp`                          | Serves `http://localhost:8000/mcp/`. |

## Local test recipe

1. **Run this MCP server** (terminal A, in the repo's `uv` env):
   ```bash
   uv run python -m astro_archives_mcp
   # health check:
   curl -s http://localhost:8000/health
   ```

2. **Set up Jupyter AI** (terminal B, a *separate* env):
   ```bash
   python -m venv ~/jai-test && source ~/jai-test/bin/activate
   pip install "jupyter-ai>=3" jupyterlab
   # the Claude persona's ACP adapter wraps the `claude` CLI, so install both (needs Node.js):
   npm install -g @anthropic-ai/claude-code @zed-industries/claude-agent-acp
   ```
   > Tip: pin a venv to Python 3.12 — the Jupyter stack may lack wheels on very new
   > Python (e.g. 3.14). `uv venv --python 3.12 .venv` works well.

3. **Register this server.** Jupyter AI reads `.jupyter/mcp_settings.json` resolved by
   walking up from the chat file's directory to the JupyterLab **root dir** (`find_dot_dir`,
   per `jupyter_ai_persona_manager`). So it lives in the directory tree JupyterLab serves —
   *not* `JUPYTER_CONFIG_DIR`. Put it at the root of your workspace:
   ```bash
   mkdir -p <jupyterlab-root>/.jupyter
   cp /path/to/astro-archives-mcp/docs/examples/mcp_settings.json \
      <jupyterlab-root>/.jupyter/mcp_settings.json
   ```
   The config:
   ```json
   {
     "mcp_servers": [
       { "type": "http", "name": "astro-archives", "url": "http://localhost:8000/mcp/" }
     ]
   }
   ```
   > **Trailing slash matters.** `POST /mcp` 307-redirects to `/mcp/` (Starlette `Mount`).
   > Use `/mcp/` directly so the integration doesn't depend on the MCP client following
   > redirects. See the gotcha in `CLAUDE.md`.

4. **Launch and test**:
   ```bash
   jupyter lab
   ```
   Open a chat, `@`-mention the agent (e.g. `@Claude`), authenticate if prompted, then ask
   something that exercises a tool, e.g.:
   > "Use the astro-archives tools to list available archives, then resolve the
   > coordinates of M51."
   The persona should call `vo_archive_list` / `vo_target_resolve`.

## gp13 deployment notes (after local works)

gp13 is a **shared JupyterHub**: it spawns a per-user single-user notebook server
(effectively a VM/container per user when they open a notebook). That changes where the
MCP server should run, because "localhost" means *inside the user's spawned VM*, not a
shared host. Two topologies:

| Topology | How it runs | Pros | Cons |
|----------|-------------|------|------|
| **A. Colocated per-VM** (recommended to start) | Bake the MCP server into the single-user image; it starts with the VM and listens on `127.0.0.1:8000`. Each user's `mcp_settings.json` points at `http://localhost:8000/mcp/`. | Isolated, no auth needed, identical to the local recipe, no cross-VM networking. | N copies of the server; bumps the image. The server is lightweight and read-only, so this is cheap. |
| **B. Shared service** | One MCP server on a host reachable from all user VMs (e.g. `http://astro-mcp.internal:8000/mcp/`). | Single deployment to operate/upgrade. | Needs network reachability from spawned VMs + likely auth once off-loopback (see `docs/adl-split.md` bearer path, `deploy/staging-runbook.md` nginx/timeout tuning). |

Because the tools are **anonymous and read-only**, topology A is the path of least
resistance for a first gp13 rollout — no auth surface, no shared-host networking, and the
config is byte-for-byte the local recipe.

- **Config delivery.** Whichever topology, `mcp_settings.json` must land where each user's
  JupyterLab reads Jupyter config. Bake it into the single-user image (system Jupyter
  config dir) so every spawned VM has it without per-user setup. Confirm the exact path
  against the gp13 image's `jupyter --paths`.
- **Agent (Claude Code) at scale.** The persona is Claude Code via its ACP adapter; every
  user's persona needs its own model auth. Options: a shared org Anthropic key provisioned
  into the image/env, or each user logging in. This is the main provisioning decision and
  is independent of this MCP server.
- **Local-model harness (exploratory).** Pointing Claude Code at a local model
  (llama.cpp, etc.) means giving Claude Code an Anthropic-compatible endpoint
  (`ANTHROPIC_BASE_URL`). llama.cpp's server speaks an OpenAI-compatible API, so it needs a
  translation shim to look Anthropic-shaped. This is orthogonal to the MCP integration —
  the MCP server works the same regardless of which model backs the persona — so prove the
  jupyter-ai → MCP path with a hosted model first, then swap the backend.
