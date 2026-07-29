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
                        MANNA (shared service)      dlai01 vLLM  (direct, ADL network)
                          http://mcp:8000/mcp/      http://dlai01…:8002
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
| The `mcp` image builds from the **working checkout** (`context: ../..`) | whatever branch the deploy host happens to be on becomes production | build from a tagged commit, and record which tag is deployed |
| `DOCKER_NETWORK=frontend_default` | spawned containers can't resolve `mcp` or the hub → the persona has no tools | set to the actual network name (`<project>_default`) |
| `mcp` publishes to **`127.0.0.1:18000`** | host-local; fine for debugging, but not how user containers should connect | user containers reach `mcp:8000` over the shared network — keep it that way, or bind an address ADL controls if the hub runs elsewhere |

All three break loudly on first use. Persistent user storage is **not** in this list —
see Deferred.

## Persona credentials

The model backend is **dlai01's vLLM, reached directly over the Astro Data Lab
network** — gp12 and dlai01 are both on it, so there is no proxy in the path:

```bash
ANTHROPIC_BASE_URL=http://dlai01.csdc.noirlab.edu:8002    # vLLM, 0.0.0.0 bind, keyless
ANTHROPIC_API_KEY=dummy                                   # see below — still required
ANTHROPIC_DEFAULT_OPUS_MODEL=Qwen/Qwen3.5-122B-A10B-FP8    # and SONNET / HAIKU
```

**This drops the `.env.example` Basic-auth setup entirely.** The
`https://datalab.noirlab.edu/astro-archives-mcp` nginx proxy exists to give *off-network*
clients (a laptop, a container elsewhere) TLS and HTTP Basic auth. On the ADL network
none of that applies, and neither does its main trap — with no Basic header there is
nothing for `ANTHROPIC_AUTH_TOKEN` to collide with. Leave `ANTHROPIC_CUSTOM_HEADERS`
unset.

**`ANTHROPIC_API_KEY=dummy` is still needed.** It has nothing to do with the proxy:
Claude Code's own login-state check needs *some* credential it recognizes, or it
intermittently declares "You're not authenticated / run `claude /login`" mid-session.
The keyless vLLM ignores it. This is expected to carry over unchanged from the proxied
setup but has not been re-validated against a direct connection — check it first.

Two consequences of dropping the proxy, worth raising with ADL ops:

- **vLLM is keyless**, so anything that can route to `dlai01:8002` can use the GPUs.
  Acceptable inside a trusted network; if not, `dlai01-vllm/docker-compose.yml` has a
  commented `--api-key` line, and that key then rides `ANTHROPIC_AUTH_TOKEN` (no
  collision, since there's no Basic header any more).
- **Traffic is plain HTTP** on the internal network — no TLS between gp12 and dlai01.

The context-window settings (`CLAUDE_CODE_MAX_CONTEXT_TOKENS` and friends) are
unaffected — they describe the model, not the transport. Keep them.

Everything above is per-user env injected by the spawner; `jupyterhub_config.py`
forwards the `ANTHROPIC_*` variables to spawned containers. Hosted Claude remains a
fallback if dlai01 is down: unset `ANTHROPIC_BASE_URL`, **comment out the
`ANTHROPIC_DEFAULT_*_MODEL` lines** (or Claude Code requests a `Qwen/…` model Anthropic
doesn't have), and supply a real credential.

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

Both items below are known gaps, deliberately out of scope for the pilot. They are
coupled: per-user storage is only meaningful once users have real identities.

### Persistent user storage — future work

Spawned containers mount **no volume**, and `DockerSpawner.remove = True`. `$HOME` lives
in the container's writable layer, so **any respawn destroys the user's notebooks and
chat history** — Stop/Start My Server in the Hub UI, an image rebuild, or a `docker rm`.
It fails silently; nothing warns the user.

For a pilot this is survivable, but only if users know. **Tell them notebooks are
scratch space, and `docker cp` anything worth keeping out before a respawn.**

Not done now because a volume alone doesn't finish the job — it introduces a second
problem that has to be solved with it:

> `mcp_settings.json` is baked into the image at `~/.jupyter/mcp_settings.json`, and the
> Jupyter AI persona layer reads it by walking up from the chat directory. **A volume
> mounted at `$HOME` covers it**, and the persona silently loses every tool — it keeps
> answering, just from the model's own knowledge. That is the hardest failure mode to
> notice, and a Docker *named* volume hides it further: it seeds itself from the image
> on first spawn, so the tools work, then freezes — later image updates to
> `mcp_settings.json` never reach existing users. A bind mount or NFS home fails
> outright.

So the work is a volume **plus** one of: seeding `~/.jupyter/` at spawn time from a
read-only staging path (e.g. `/opt/manna/`) so it lands after the mount, or mounting the
volume below `$HOME` (`~/work`) and leaving `~/.jupyter/` as image content. Add a
backup/retention story and it stops being a one-line config change — hence deferred.

### Auth — future work

Hub mode ships `DummyAuthenticator`: one shared password from
`JUPYTERHUB_DUMMY_PASSWORD`, any username accepted, no per-user identity. Accepted for
internal NRAO/ADL use during the pilot.

Replace it with a real authenticator before gp12 is reachable by anyone outside the
team, and **before** persistent storage lands — with dummy auth, any user can log in
under any other username and would get that user's files.

## Open questions for ADL ops

- **Does ADL already run a JupyterHub on gp12 that we plug into**, or do we deploy the
  hub from `frontend/`? If it's ADL's, we supply the single-user image plus the shared
  MCP service and they point their spawner at it.
- **Spawner and base image** — DockerSpawner? KubeSpawner? A bespoke VM image?
- **Does ADL's spawner already mount home directories?** If it does, deferring persistent
  storage is not actually available to us: the mount lands on `$HOME` on day one and
  shadows `~/.jupyter/mcp_settings.json`, so the spawn-time seeding described under
  Deferred becomes required before first use, not future work.
- **Where does the MCP service live**, and how do user containers route to it — the
  same docker network, a cluster service, or a hostname ADL provides?
- **Can gp12 actually route to `dlai01:8002`**, and is leaving vLLM keyless on that
  network acceptable? Both assumed above, neither confirmed.
