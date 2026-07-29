# Integrating MANNA with Jupyter AI

Status: working notes / local-test recipe. Target deployment: Astro Data Lab notebook
server **gp12**, surfacing the VO tools to notebook users via Jupyter AI chat.

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
> enumerates all 11 `vo_*` tools. A bare `POST /mcp` (no slash) returns a 307 redirect to
> `/mcp/`, so always configure the trailing-slash URL.

## Large results: the `fetch_recipe` flow

The server is **stateless** — it never holds result bytes (see the "Result handling"
section in `CLAUDE.md`). A small query result comes back inline in the tool response, but
a large one is routed to an async TAP job and `vo_tap_results` returns a `job_url`, a
`result_url`, and a **`fetch_recipe`** — a snippet of runnable pyvo code — instead of the
data. The persona is expected to **run that snippet in the user's notebook kernel**, where
the data lands as a local `table` the user can keep analyzing:

```
persona: vo_tap_query(mode='async')  → job_url + job_id
persona: vo_tap_status(job_id)       → COMPLETED
persona: vo_tap_results(job_id)      → { result_url, fetch_recipe: { code: "import pyvo; …" } }
persona: <Jupyter_MCP_Server: insert + execute a cell with fetch_recipe.code>
kernel:  table = job.fetch_result().to_table()   # real astropy.Table, in the user's session
```

This is why the persona is wired to **two** MCP servers (see `deploy/frontend/`): our
`manna` tools *and* a notebook-control server (`Jupyter_MCP_Server`) that lets it
write and run cells. A chat-only persona with no code-execution surface can still use the
discovery/metadata tools, but cannot materialize a large result — it can only hand the
`fetch_recipe`/`result_url` to the user to run themselves.

> **Verified end-to-end** (against ALMA, anonymous): the exact `fetch_recipe.code` emitted
> by `vo_tap_results`, executed in a fresh Python namespace as a kernel cell would, loaded
> a real `astropy.Table`. The recipe uses `pyvo.dal.AsyncTAPJob(job_url).fetch_result()`,
> which resolves the archive-specific result URL internally — it does not depend on the
> `result_url` scheme (which differs per archive: GAVO `/results/result`, ALMA
> `/tap/files/result_<id>.xml`, Data Lab `/resultStore/result_<id>.xml`).

## Prerequisites

| Component        | Install                                                        | Notes |
|------------------|----------------------------------------------------------------|-------|
| JupyterLab 4 + Jupyter AI v3 | `pip install jupyter-ai` (or conda-forge)          | Use a **separate env** from this server's `uv` env. |
| Node.js          | conda/system package                                           | Required by the Claude Code ACP adapter. |
| An ACP agent     | `npm install -g @anthropic-ai/claude-code @zed-industries/claude-agent-acp` | Provides the `claude-agent-acp` binary the Claude persona launches; it wraps the `claude` CLI for auth/model calls, so install both (verified against `jupyter_ai_acp_client` 0.1.5). npm warns the adapter was renamed to `@agentclientprotocol/claude-agent-acp` — either works today. |
| Agent auth       | reuse your existing Claude Code login                          | The Claude persona wraps the `claude` CLI's own auth, so if you already use Claude Code you're set. If a token is expired the persona replies telling you to run `claude /login`. No separate API key step. |
| This MCP server  | `uv run python -m manna`                          | Serves `http://localhost:8000/mcp/`. |

## Local test recipe

1. **Run this MCP server** (terminal A, in the repo's `uv` env):
   ```bash
   uv run python -m manna
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
   cp /path/to/manna/docs/examples/mcp_settings.json \
      <jupyterlab-root>/.jupyter/mcp_settings.json
   ```
   The config:
   ```json
   {
     "mcp_servers": [
       { "type": "http", "name": "manna", "url": "http://localhost:8000/mcp/" }
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
   Open a chat, `@`-mention the agent (e.g. `@CosmicCoder` in the deploy images, or the
   stock `@Claude` in a plain install), authenticate if prompted, then ask
   something that exercises a tool, e.g.:
   > "Use the MANNA tools to list available archives, then resolve the
   > coordinates of M51."
   The persona should call `vo_archive_list` / `vo_target_resolve`.

## Renaming the persona (`@claude` → `@CosmicCoder`)

The deploy image (`deploy/frontend/frontend.Dockerfile`) presents the agent as
**`@CosmicCoder`** rather than the stock `@Claude`. This is a
CosmicAI rebrand only — the underlying engine (`claude-agent-acp` wrapping the `claude`
CLI), model backend, and MCP tools are unchanged.

Why it's done by patching the installed package rather than by config:

- Personas are discovered via the `jupyter_ai.personas` entry-point group and instantiated
  by `PersonaManager`. As of **jupyter-ai 3.0.1 / jupyter-ai-acp-client 0.1.5** there is
  **no allow/block/disable trait** for personas, and local `.jupyter/personas/` files only
  *add* personas — so you cannot hide the stock `@Claude` via configuration. (The
  declarative `.persona.md` + "disable default persona" work is a jupyter-ai **3.2**
  roadmap item; 3.2 is unreleased, and that roadmap still lists the disable piece as
  unresolved.)
- The chat `@`-handle is derived from the persona's **display name** by
  `jupyterlab_chat.models.User.mention_name` = `display_name.replace(" ", "-")` (no
  lowercasing). So the display name **is** the handle. We set it to the exact string
  `CosmicCoder` (no space) to get the literal `@CosmicCoder`. A space-separated
  `"Cosmic Coder"` label would instead render as `@Cosmic-Coder`.

So the Dockerfiles override `ClaudeAcpPersona.defaults` (name/description/avatar) in the
**pinned** installed `jupyter_ai_acp_client/acp_personas/claude.py`. The versions are
pinned precisely so this in-place patch stays deterministic; the build includes `grep`
guards that fail if a version bump moves the patched lines. To bump jupyter-ai, update the
pins and re-verify the patch still matches.

## gp12 deployment

gp12 is a **shared JupyterHub**: it spawns a per-user single-user notebook server when a
user opens a notebook. That changes where the MCP server runs, because "localhost" means
*inside the user's spawned container*, not a shared host. MANNA is deployed there as
**one shared MCP service** that every spawned container reaches over the network — the
tools are anonymous, read-only, and hold no per-user state, so a single instance serves
everyone.

Two things still have to be true per user, whatever the hub does: `mcp_settings.json`
must land where that user's JupyterLab reads Jupyter config (baked into the single-user
image at `~/.jupyter/`), and the persona needs model credentials injected by the spawner.

See **`deploy/gp12-runbook.md`** for the deployment procedure, and
**`deploy/frontend/README.md`** for the stack it deploys.
