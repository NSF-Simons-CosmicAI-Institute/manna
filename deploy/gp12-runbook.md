# gp12 Deployment Runbook — MANNA via Jupyter AI

Surface MANNA's VO tools to notebook users on Astro Data Lab's **gp12** through the
Jupyter AI persona. MANNA runs as **one shared MCP service** on the host's loopback;
every user's notebook server reaches it at `http://127.0.0.1:8000/mcp/`.

Status: **validated end-to-end on gp12, 2026-07-30** — for a staff account. Not yet
validated for a jailed Data Lab user, which is blocked on one thing (see *Blockers*).

> **The proof.** In JupyterLab chat on gp12: `@Claude resolve galaxy m51 using MANNA
> mcp tools` → `✓ mcp__manna__vo_target_resolve` → RA 202.469575°, Dec +47.19525833°
> (ICRS), with a matching `CallToolRequest` in the MANNA container log. The full chain:
> persona → `claude-agent-acp` → `claude` → gpt-oss-120b on dlai01 → MANNA → a real
> IVOA resolver call.

## What gp12 actually is

gp12 runs **its own JupyterHub** — we do not deploy one. Established by inspection,
2026-07-30:

| | |
|---|---|
| Hub | JupyterHub 4.0.2 from `/data0/sw/anaconda3`, config `/root/ssl.jupyterhub_config.py` |
| Public face | `configurable-http-proxy` on **:443**, TLS, `gp12.datalab.noirlab.edu` |
| Spawner | **`LocalProcessSpawner`** — user servers are local processes on the host |
| Auth | `dlauthenticator.DataLabAuthenticator` — real Data Lab accounts |
| Users | `/home/jail/dlusers` (NFS, ~5100 accounts), chrooted to `/home/jail` |
| Idle culling | `jupyterhub_idle_culler --timeout=21600` (6h) |
| Stack | Python 3.10.13, JupyterLab 4.1.5, **jupyter-ai 3.0.1** already installed |

**jupyter-ai was already there**, at versions matching our Docker image exactly
(`jupyter-ai` 3.0.1, `jupyter-ai-acp-client` 0.1.5, `jupyter-server-documents` 0.2.5,
`jupyterlab-chat` 0.22.1, …). We install no Python packages on gp12.

Because the spawner is local, **loopback is shared** between the MCP container and every
user server. No container networking, no service discovery, no off-host exposure.

```
gp12 JupyterHub (:443) ──spawns──► user server (local process, Jupyter AI persona)
                                          │                    │
                                MCP tools │                    │ model
                                          ▼                    ▼
                          MANNA container                dlai01 vLLM
                          127.0.0.1:8000                 dlai01.csdc.noirlab.edu:8002
```

## What we deploy

Three things. Only the first is ours to run as a service.

### 1. MANNA container

```bash
git clone https://github.com/dangause/manna.git ~/manna && cd ~/manna
git checkout dev                       # or a release tag
docker build -t manna:dev .
docker run -d --name manna --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  -e MANNA_HOST=0.0.0.0 -e MANNA_PORT=8000 -e MANNA_DEPLOYMENT=adl \
  manna:dev
curl -fsS http://127.0.0.1:8000/health          # {"status":"ok","version":"0.5.0",...}
```

`MANNA_HOST=0.0.0.0` is the bind *inside* the container; `-p 127.0.0.1:8000:8000`
keeps it on host loopback. For a real deployment this should be a systemd unit rather
than an ad-hoc `docker run` in someone's home.

### 2. The persona harness (needs ops)

`claude-agent-acp` and `claude` are **not services** — the persona spawns them as
subprocesses, so they must be executable from the user's server process. They must land
in the **only tree bind-mounted into the jail**, `/data0/sw/anaconda3`:

```bash
npm config set prefix /data0/sw/anaconda3
npm install -g @anthropic-ai/claude-code @zed-industries/claude-agent-acp
```

This requires **node ≥ 22** (see *Blockers*).

### 3. System Jupyter config (needs ops)

`/data0/sw/anaconda3/etc/jupyter/jupyter_server_config.py` — a `.py` file in that
directory, **not** in `jupyter_server_config.d/` (that one only takes JSON extension
toggles):

```python
import os

# IPv6 is disabled on this host; `localhost` resolves to ::1 and binds fail.
c.MCPServer.host = "127.0.0.1"

# Model backend: dlai01 vLLM, direct over the ADL network. No proxy, keyless.
os.environ.setdefault("ANTHROPIC_BASE_URL", "http://dlai01.csdc.noirlab.edu:8002")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("ANTHROPIC_DEFAULT_OPUS_MODEL", "openai/gpt-oss-120b")
os.environ.setdefault("ANTHROPIC_DEFAULT_SONNET_MODEL", "openai/gpt-oss-120b")
os.environ.setdefault("ANTHROPIC_DEFAULT_HAIKU_MODEL", "openai/gpt-oss-120b")
os.environ.setdefault("CLAUDE_CODE_MAX_OUTPUT_TOKENS", "4096")
os.environ.setdefault("CLAUDE_CODE_MAX_CONTEXT_TOKENS", "131072")
os.environ.setdefault("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "120000")
os.environ.setdefault("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE", "85")
os.environ.setdefault("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")

# MCP servers handed to the persona. Setting this REPLACES the default, whose URL
# uses `localhost` — see Gotchas.
c.PersonaManager.builtin_mcp_servers = [
    {"type": "http", "name": "manna", "url": "http://127.0.0.1:8000/mcp/", "headers": []},
    {"type": "http", "name": "Jupyter MCP Server", "url": "http://127.0.0.1:3001/mcp", "headers": []},
]
```

**`builtin_mcp_servers` is the delivery mechanism**, confirmed 2026-07-30: with the
CLI-scope entry removed from `~/.claude.json`, the persona still had the tools. This is
why nothing needs writing into users' NFS homes.

Per-user tool pre-approval still lives in each user's home, and without it the persona
asks permission for every call:

```json
// ~/.claude/settings.json
{"permissions": {"allow": ["mcp__manna", "mcp__Jupyter_MCP_Server"]}}
```

## Blockers

**Node is too old in the jail.** `@anthropic-ai/claude-code` 2.1.220 declares
`engines: {"node": ">=22.0.0"}`. gp12 has:

| Path | Version | Visible in jail? |
|---|---|---|
| `/usr/bin/node` | v26.5.0 | **no** — jail's `/usr/bin` is curated, no node |
| `/data0/sw/anaconda3/bin/node` | **v18.16.0** | yes |

So a jailed Data Lab user cannot run the harness today. Either upgrade nodejs in the
anaconda env, or install a modern node side-by-side (e.g.
`/data0/sw/anaconda3/opt/node22`) and prepend it to `PATH` in the system config. The
side-by-side option is lower risk on a shared env and is what should transfer to gp13.

**Everything validated so far used a staff account** (`dgause`, local home, host node
v26.5.0) — not a jailed `dlusers` account. A second validation round inside the jail is
required before this is real for users.

## Verify

```bash
# 1. Service up (from the host)
curl -fsS http://127.0.0.1:8000/health

# 2. Protocol + tools
npx -y @modelcontextprotocol/inspector --cli http://127.0.0.1:8000/mcp --method tools/list
# → 12 tools: vo_archive_list, vo_tap_query, vo_target_resolve, …

# 3. Harness, from a user's server (model path only)
claude -p "say ok"

# 4. End-to-end, in JupyterLab chat
#    @Claude resolve galaxy m51 using MANNA mcp tools
docker logs --tail 5 manna
```

Success on step 4 = **RA 202.4696, Dec +47.195** *and* a fresh `CallToolRequest` in the
container log. A confident answer with nothing in the log is the model guessing.

Do **not** use `claude mcp list` as a check — see Gotchas.

## Gotchas (all hit on 2026-07-30)

- **IPv6 is disabled host-wide** (`disable_ipv6=1`, site policy — "we don't use IPv6
  here"). Anything resolving `localhost` gets `::1` and fails with errno 99. Use the
  `127.0.0.1` literal everywhere. This crashed `jupyter_server_mcp` on startup, which
  killed the single-user server, which surfaced as a 60s hub spawn timeout — three
  layers away from the cause.
- **`builtin_mcp_servers`' default URL uses `localhost`.** The default entry for the
  Jupyter MCP Server is built as `http://localhost:{mcp_port}/mcp`, so on this host it
  points at a dead address. Setting the trait explicitly (above) replaces it.
- **`claude mcp list` is not a valid check — twice over.** It reads the `claude` CLI's
  own config, not the persona's, so it reports "No MCP servers configured" when the
  persona works fine; and it reported `ConnectionRefused` against a server that was
  reachable and serving. The container log is the only trustworthy signal.
- **A healthy container can have a dead port binding.** Killing host processes can take
  out `docker-proxy` while the container keeps running — `docker ps` shows `Up
  (healthy)` and its own healthcheck passes, but nothing listens on the host.
  `docker restart` recreates the binding; `docker start` on a running container is a
  no-op.
- **`jupyter_server_mcp` binds a fixed port 3001.** With `LocalProcessSpawner` every
  user server runs on the same host, so concurrent users may collide. **Untested** —
  raise with ADL ops before rollout. MANNA does not need this extension; disabling it
  removes both this and the IPv6 problem.
- **Config must be `jupyter_server_config.py`**, not a file under
  `jupyter_server_config.d/` (JSON extension toggles only), and it is a *Jupyter Server*
  setting — putting `c.MCPServer.host` in the JupyterHub config does nothing.
- **Username/home mismatches break everything silently.** A duplicate-UID account left
  the hub spawning as one user while the shell was another, so none of the per-user
  config was read and the persona sat mute with no error anywhere. If the persona is
  silent, check `whoami` and `$HOME` *inside the spawned server* first.

## Not done yet

- **Jailed-user validation** — the blocker above, then re-run Verify as a `dlusers` account.
- **MANNA as a managed service** — systemd unit, pinned image tag, restart policy.
- **Multi-user concurrency** — the port 3001 question.
- **Persona rebrand** (`@CosmicCoder` + astronomy role framing). Cosmetic; it patches
  `jupyter_ai_acp_client` in a shared env and reverts on any package upgrade. The
  `~/.claude/CLAUDE.md` role framing is per-user and needs no privileges. See
  `frontend/README.md`.
- **gp13 promotion.** gp13 is production; gp12 is the sandbox. Everything here should be
  reproducible as ops-owned config, not hand edits.

## Open questions for ADL ops

- Who owns the MANNA container long-term, and where should it be defined as a service?
- Upgrade nodejs in `/data0/sw/anaconda3`, or install node ≥22 side-by-side?
- Is the fixed port 3001 a real multi-user problem here, and has gp13 seen it?
- Should the persona be rebranded for Data Lab users, and whose call is that?
