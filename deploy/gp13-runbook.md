# gp13 Deployment Runbook — astro-archives-mcp via Jupyter AI

Status: **design draft** for review by ADL ops. Goal: surface the VO tools to
notebook users on Astro Data Lab's **gp13**, a shared JupyterHub that spawns a
per-user single-user server (VM/container) per session, through **Jupyter AI v3**
chat. See `docs/jupyter-ai-integration.md` for the architecture.

> **What's proven, and where.** The full persona chain — Jupyter AI's Claude
> persona → `claude-agent-acp` → `claude` CLI → this MCP server over HTTP →
> a live VO tool call — was validated **headless on dlai01 (2026-06-29)**:
> `claude mcp add --transport http`, `claude mcp list` → Connected, and a
> `claude -p` call that invoked `vo_target_resolve` for M51 (RA 202.47 /
> Dec +47.20), not a guess. The container packaging of that same chain
> (`docs/examples/gp13/`) is exercised by `smoke-test.sh` (below). gp13 itself is
> pending access; this runbook is what plugs the proven image into its spawner.

> **Assumptions flagged for ADL ops** (confirm before building — they change the
> mechanics below):
> 1. The single-user image derives from **jupyter/docker-stacks** (so
>    `before-notebook.d/` start hooks exist). If it's a bespoke image or VM, the
>    hook becomes a systemd unit / entrypoint line instead.
> 2. Each user's **`$HOME` is a writable, non-tiny volume**. astropy & pyvo write
>    caches under `~/.astropy` and `$TMPDIR`; a read-only or full volume makes
>    every `vo_target_resolve` / `vo_registry_search` fail with `archive_error`
>    (we hit exactly this with a disk-full container in testing).
> 3. The chosen **persona LLM backend** (hosted Claude vs. local model on dlai01)
>    and how its credentials are provisioned — see §4.

## Topology: colocated vs. shared

| | **A. Colocated (recommended to prove first)** | **B. Shared service** |
|---|---|---|
| Where | MCP server runs *inside* each single-user server on `127.0.0.1` | One MCP deployment all user pods reach over the cluster network |
| Config URL | `http://127.0.0.1:8000/mcp/` | `http://astro-mcp.<ns>:8000/mcp/` |
| Auth | none (loopback, anonymous read-only tools) | none needed (anonymous), but exposed off-loopback → see `deploy/staging-runbook.md` proxy/timeout notes |
| Pros | identical to the proven recipe, zero network/auth surface, per-user isolation | one upgrade path, no per-user process/cache duplication |
| Cons | N server processes + N astropy caches | requires user-pod → service reachability; one shared blast radius |

Because the tools are anonymous and read-only, **A** is the path of least resistance
to a first rollout and is what the rest of this runbook details. **B** becomes
attractive once it's proven and you want a single thing to operate/upgrade — at
that point deploy the existing container (see `deploy/staging-runbook.md`) as a
cluster service and only change the config URL.

## The single-user image (Topology A)

The reference image lives at **`docs/examples/gp13/`** (Dockerfile + startup hook +
config + `build.sh` + `smoke-test.sh`). Build and smoke-test it **on a box with a
working docker** (e.g. dlai01):

```bash
cd docs/examples/gp13
./build.sh                                  # BASE_IMAGE=<adl-base> ./build.sh once known
export CLAUDE_CODE_OAUTH_TOKEN=$(claude setup-token)   # optional: enables the live tool-call check
IMAGE=astro-archives-singleuser:dev ./smoke-test.sh
```

> **Build from the example dir as context, not the repo root.** The repo-root
> `.dockerignore` excludes `docs/`, `deploy/`, `tests/`, so a repo-root context
> can't `COPY` the hook or config. `build.sh` already uses the right context.

What the image adds, and why:

1. **Python deps** — Jupyter AI v3 + this server, pinned to a tag:
   ```dockerfile
   RUN pip install --no-cache-dir "jupyter-ai>=3" jupyterlab \
       "astro-archives-mcp @ git+https://github.com/dangause/astro-archives-mcp.git@v0.3.0"
   ```

2. **Node.js + BOTH persona binaries.** The Claude persona launches
   `claude-agent-acp`, which wraps the `claude` CLI for auth and model calls, so
   both must be present:
   ```dockerfile
   RUN npm install -g @anthropic-ai/claude-code @zed-industries/claude-agent-acp
   ```
   (npm warns the adapter was renamed to `@agentclientprotocol/claude-agent-acp`;
   either works.) Skip this stage if backing the persona with a local model (§4).

3. **Start the MCP server on loopback at spawn** — the
   `before-notebook.d/10-astro-archives-mcp.sh` hook launches it in the background
   on `127.0.0.1:8000` with writable cache env, and is idempotent.

4. **Seed the MCP config robustly.** The hook copies `mcp_settings.json` from a
   read-only staging path (`/opt/astro-archives/`) into `~/.jupyter/` **at spawn
   time** — so it lands *after* any persistent-`$HOME` volume mounts, which would
   otherwise shadow a file baked into the image's home. This sidesteps the
   "fresh vs. persistent `$HOME`" question entirely: it works either way.

> Optional hardening: pre-warm the pyvo/astropy vocabulary cache at build time
> (`RUN python -c "from pyvo.utils import vocabularies as v; v.get_vocabulary('messenger')"`)
> so the first user query doesn't pay a network+disk hit.

## 4. Persona credentials at scale (the main ADL decision)

The persona authenticates exactly like the `claude` CLI — it reads credentials
from `$CLAUDE_CONFIG_DIR` (default `~/.claude`) or from env. The image ships **no
secret**; the spawner injects one of these (independent of the MCP server):

- **Shared org credentials** (simplest multi-user v1) — inject an NRAO/CosmicAI
  `ANTHROPIC_API_KEY` (or a long-lived `CLAUDE_CODE_OAUTH_TOKEN` from
  `claude setup-token`) into the single-user env via the spawner. Shared billing &
  governance. Optionally pin an account with `CLAUDE_CONFIG_DIR`.
- **Per-user login** — each user runs `claude /login` once; creds persist in their
  home volume. No shared secret; users need their own Anthropic access.
- **Local model on dlai01** — point Claude Code at an on-prem model via
  `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN`. No per-call cost, data stays on-prem;
  tool-use quality depends on the model. Orthogonal to everything above — the MCP
  path is unchanged. See **`docs/local-model-backend.md`** for the researched PoC
  stack (vLLM native Anthropic endpoint + Qwen3 + parser flags) and the
  Blackwell/sm_120 serving gotchas.

## Verify

**Interim (no gp13 access): container smoke test on dlai01** — `smoke-test.sh`
covers /health, persona binaries, seeded config, `claude mcp list → Connected`,
and (with a token) a live M51 tool call inside the image.

**On gp13 (once available), inside a spawned single-user server:**
```bash
curl -fsS http://127.0.0.1:8000/health                       # astro-archives 0.3.0
cat ~/.jupyter/mcp_settings.json                             # points at 127.0.0.1:8000/mcp/
ps eww $(pgrep -f 'jupyter-lab') | tr ' ' '\n' | grep CLAUDE_CONFIG_DIR  # if pinning an account
```
Then in JupyterLab chat: `@Claude use the astro-archives tools to resolve M51.`
Success = the server log shows a `CallToolRequest` and the reply carries real
coordinates (RA 202.47, Dec +47.20), not a model guess.

## Open questions for ADL ops

- Spawner & base image (docker-stacks? KubeSpawner/DockerSpawner? bespoke VM)?
- Is `$HOME` per-spawn-fresh or a persistent volume? (the hook handles both, but
  confirm so we can drop the belt-and-suspenders if it's always fresh)
- Persona backend + credential model (§4)?
- Topology A vs. B for the operated rollout?
