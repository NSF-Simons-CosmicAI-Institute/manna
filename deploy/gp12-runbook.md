# gp12 Deployment Runbook — MANNA via Jupyter AI

Surface MANNA's VO tools to notebook users on Astro Data Lab's **gp12** through a
**Jupyter AI v3** persona (`@CosmicCoder`). MANNA runs as **one shared MCP service**
that every spawned user container reaches over the network.

Status: **design draft** for ADL ops. The stack itself is validated — a hub-spawned
single-user container's persona resolved M51 via a real `vo_target_resolve` call
through the dlai01 vLLM (2026-07-02, macOS/arm64), and Verify steps 1–3 below were
re-run against a live hub-spawned container on 2026-07-29. What's unproven is gp12
itself: its spawner, its network, and an amd64 rebuild.

This runbook covers only what is **gp12-specific**. How the stack works, its
configuration, and its gotchas live in **`frontend/README.md`** — read that first.

## Architecture

```
gp12 JupyterHub ──spawns──► user container (Jupyter AI + @CosmicCoder persona)
                                    │                      │
                          MCP tools │                      │ model
                                    ▼                      ▼
                        MANNA (shared service)    datalab nginx proxy ──► dlai01 vLLM
                          http://mcp:8000/mcp/    ANTHROPIC_BASE_URL
```

Model and tools are **independent connections** — the persona reaches the model over
`ANTHROPIC_BASE_URL` and the tools over the MCP URL; neither knows about the other.

**One MCP deployment serves everyone.** The tools are anonymous, read-only, and the
server never persists result bytes, so there is no per-user state to isolate — a single
instance is correct, not just convenient, and users share one astropy/pyvo cache.

## What to deploy

Everything comes from **`frontend/`**, hub profile — `mcp` (the shared tool server)
plus `hub` (JupyterHub + DockerSpawner), which spawns the `lab` image per user:

```bash
cd deploy/frontend
cp .env.example .env          # model endpoint + persona credentials
docker compose build lab      # the single-user image DockerSpawner launches
docker compose --profile hub up --build
```

The trailing slash on `/mcp/` matters: `POST /mcp` 307-redirects (Starlette `Mount`).

## What must change from the dev defaults

`frontend/` is wired for local development. Four things are wrong for gp12:

| Default | Why it breaks on gp12 | Change |
|---|---|---|
| Spawned containers get **no volume**, and `DockerSpawner.remove = True` | `$HOME` is ephemeral — a respawn silently wipes the user's notebooks | mount a per-user volume — but see the shadowing trap below |
| The `mcp` image builds from the **working checkout** (`context: ../..`) | whatever branch the deploy host happens to be on becomes production | build from a tagged commit, and record which tag is deployed |
| `DOCKER_NETWORK=frontend_default` | spawned containers can't resolve `mcp` or the hub → the persona has no tools | set to the actual network name (`<project>_default`) |
| `mcp` publishes to **`127.0.0.1:18000`** | host-local; fine for debugging, but not how user containers should connect | user containers reach `mcp:8000` over the shared network — keep it that way, or bind an address ADL controls if the hub runs elsewhere |

The volume is the only silent failure of the four; the rest break loudly on first use.

### The `$HOME` volume shadows the persona config

`mcp_settings.json` is baked into the image at `~/.jupyter/mcp_settings.json`, and the
Jupyter AI persona layer reads it by walking up from the chat directory. **Mounting a
volume at `$HOME` covers it**, and the persona silently loses every tool — it keeps
answering, just from the model's own knowledge, which is exactly the failure mode
hardest to notice.

The two defaults collide: fixing the ephemeral-`$HOME` problem creates this one. Pick one:

- **Seed at spawn time** — stage the file read-only in the image (e.g. `/opt/manna/`)
  and copy it into `~/.jupyter/` from a startup hook, so it lands *after* the volume
  mounts. Works whether `$HOME` is fresh or persistent.
- **Mount below `$HOME`** — give the volume a subdirectory (`~/work`) and leave
  `~/.jupyter/` as image content.

A Docker *named* volume hides the collision: it seeds itself from the image on first
spawn, so the tools work — then freeze at that version, and later image updates to
`mcp_settings.json` never reach existing users. A bind mount or NFS home fails outright.

## Persona credentials

Every user's persona needs model auth. The image ships no secret — the spawner injects
it, and `jupyterhub_config.py` forwards the `ANTHROPIC_*` env to spawned containers.

- **Local model on dlai01** — `ANTHROPIC_BASE_URL` at the datalab nginx proxy. No
  per-call cost, data stays on-prem, and it's the validated path (`dlai01-vllm-runbook.md`).
- **Shared org credential** — one NRAO/CosmicAI credential in the hub's env, forwarded
  to every user. Shared billing and governance.
- **Per-user login** — `claude /login` once per user, credentials persist in their home
  volume. No shared secret, but each user needs their own Anthropic access.

Variables and their collisions — the Basic-auth vs. `ANTHROPIC_AUTH_TOKEN` trap in
particular — are in `frontend/.env.example`.

## Verify

Steps 1–3 need no model credentials — they check the tool path only. Step 4 is the
end-to-end and needs the model backend up.

**1. The service is up** (on the gp12 host):

```bash
curl -fsS http://localhost:18000/health        # {"status":"ok","version":"0.5.0",...}
```

**2. It speaks MCP and exposes the tools** (from anywhere that can reach it):

```bash
npx -y @modelcontextprotocol/inspector --cli http://localhost:18000/mcp --method tools/list
# → 12 tools: vo_archive_list, vo_tap_query, vo_target_resolve, …
```

**3. A spawned user container can reach it, and has the persona config** (`docker exec`
into a running single-user container):

```bash
curl -fsS http://mcp:8000/health               # the cross-container hop works
cat ~/.jupyter/mcp_settings.json               # → url: http://mcp:8000/mcp/
```

Note it is **`~/.jupyter/mcp_settings.json`**, read by the Jupyter AI persona layer —
*not* `claude mcp list`. The `claude` CLI keeps its own separate MCP config and will
report "No MCP servers configured" even when the persona's tools work perfectly.

**4. End-to-end**, in JupyterLab chat: `@CosmicCoder use the MANNA tools to resolve M51.`

Success = the `mcp` service log shows a `CallToolRequest` **and** the reply carries real
coordinates (RA 202.4696, Dec +47.195). A plausible-looking answer with no tool call in
the log is a failure, not a pass.

## Deferred

**Auth — intentionally not addressed.** Hub mode ships `DummyAuthenticator`: one
shared password from `JUPYTERHUB_DUMMY_PASSWORD`, any username accepted, no per-user
identity. Accepted for internal NRAO/ADL use during the pilot.

Replace it with a real authenticator before gp12 is reachable by anyone outside the
team, or before per-user state means anything — with dummy auth, any user can log in
under any other username and get that user's home volume.

## Open questions for ADL ops

- **Does ADL already run a JupyterHub on gp12 that we plug into**, or do we deploy the
  hub from `frontend/`? If it's ADL's, we supply the single-user image plus the shared
  MCP service and they point their spawner at it.
- **Spawner and base image** — DockerSpawner? KubeSpawner? A bespoke VM image?
- **Where does the MCP service live**, and how do user containers route to it — the
  same docker network, a cluster service, or a hostname ADL provides?
- **Persona credential model** — which of the three above?
