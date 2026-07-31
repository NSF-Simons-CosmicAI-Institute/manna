# gp12 Deployment Runbook — MANNA via Jupyter AI

Surface MANNA's VO tools to notebook users on Astro Data Lab's **gp12** through the
Jupyter AI persona. MANNA runs as **one shared MCP service** on the host's loopback;
every user's notebook server reaches it at `http://127.0.0.1:8000/mcp/`.

Status: **validated end-to-end on gp12** — from a user's home config 2026-07-30, then
from **system config** 2026-07-31 with the per-user config removed, which is what proves
it works for users other than the one who set it up. Not yet validated for a *jailed*
Data Lab user, which is blocked on one thing (see *Blockers*).

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

### 1. MANNA container (needs ops)

The checkout lives with the rest of the Astro Data Lab software in **`/data0/sw/`**,
not in a user's home. Note `/data0/sw` is a symlink to `sw.tmpfs`, which despite the
name is persistent local XFS on `/dev/sdc`.

```bash
git clone https://github.com/dangause/manna.git /data0/sw/manna
cd /data0/sw/manna && git checkout v0.5.0          # a tag, not a branch
docker build -t manna:v0.5.0 .
```

> **No release tag exists yet** — the repo has never been tagged. Cut `v0.5.0` from a
> promoted `main` before deploying, or pin a commit SHA in the meantime. Do not deploy
> from `dev`: it moves, and the deployed version would silently change on every rebuild.

Then run it as a systemd unit rather than an ad-hoc `docker run`, so it survives
reboots and any user can't be the single point of failure:

```ini
# /etc/systemd/system/manna.service
[Unit]
Description=MANNA MCP server (IVOA archive tools for Jupyter AI)
Documentation=https://github.com/dangause/manna
After=docker.service
Requires=docker.service

[Service]
Restart=always
RestartSec=5
ExecStartPre=-/usr/bin/docker rm -f manna
ExecStart=/usr/bin/docker run --rm --name manna \
  -p 127.0.0.1:8000:8000 \
  -e MANNA_HOST=0.0.0.0 -e MANNA_PORT=8000 -e MANNA_DEPLOYMENT=adl \
  manna:v0.5.0
ExecStop=/usr/bin/docker stop manna

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload && systemctl enable --now manna
curl -fsS http://127.0.0.1:8000/health          # {"status":"ok","version":"0.5.0",...}
```

`MANNA_HOST=0.0.0.0` is the bind *inside* the container; `-p 127.0.0.1:8000:8000` keeps
it on host loopback, which is all that's needed — user servers are local processes on
the same host.

**This directory does not need to be jail-visible.** Users reach MANNA over loopback and
never touch its files, so `/data0/sw/manna` being outside the jail's bind mounts is
fine. That is the opposite of the persona harness below, which *must* be jail-visible.

To upgrade: `git fetch && git checkout <newtag>`, rebuild with the new tag, update
`ExecStart`, then `systemctl daemon-reload && systemctl restart manna`.

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

# The persona spawns `claude-agent-acp`, which must be on PATH.
#
# Do NOT prepend /data0/sw/anaconda3/bin: its node is v18.16.0, and `claude` is a
# node script resolved via `#!/usr/bin/env node`, so putting it first silently
# downgrades the interpreter below claude-code's `>=22` and the harness dies after
# listing tools. Once ops installs node >=22, that bin dir must come BEFORE the
# anaconda prefix. See Gotchas.
os.environ["PATH"] = ":".join([
    os.path.join(os.path.expanduser("~"), ".npm-global/bin"),   # transitional
    os.environ.get("PATH", "/usr/bin:/bin"),
])

# MCP servers handed to the persona. Setting this REPLACES the default, whose URL
# uses `localhost` — see Gotchas.
c.PersonaManager.builtin_mcp_servers = [
    {"type": "http", "name": "manna", "url": "http://127.0.0.1:8000/mcp/", "headers": []},
    {"type": "http", "name": "Jupyter MCP Server", "url": "http://127.0.0.1:3001/mcp", "headers": []},
]
```

**`builtin_mcp_servers` is the delivery mechanism**, confirmed twice: 2026-07-30 with
the CLI-scope entry removed from `~/.claude.json`, and 2026-07-31 with the user's entire
`~/.jupyter/jupyter_server_config.py` moved aside. Nothing needs writing into users' NFS
homes.

> On gp12 this file can be installed without full root. Randy scoped a sudo rule to the
> exact command `cp jupyter_server_config.py /data0/sw/anaconda3/etc/jupyter/` — note it
> matches a **relative** filename, so run it from a directory holding a file by that
> name. No hub restart is needed; each single-user server reads this at spawn. Always
> `compile()`-check first: a syntax error here breaks spawns for every account on the
> host.

**Unsolved: per-user tool pre-approval.** Without this file the persona asks permission
for every call, and it lives in each user's home — the one piece of config with no
system-wide home yet:

```json
// ~/.claude/settings.json
{"permissions": {"allow": ["mcp__manna", "mcp__Jupyter_MCP_Server"]}}
```

Candidate fixes, neither verified: a Claude Code managed-settings path, or pointing
`CLAUDE_CONFIG_DIR` at a shared read-only directory from the config above.

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

# 3. Loopback reaches the jail — run from a JAILED user's terminal
curl -fsS http://127.0.0.1:8000/health

# 4. Harness, from a user's server (model path only)
claude -p "say ok"

# 5. End-to-end, in JupyterLab chat
#    @Claude resolve galaxy m51 using MANNA mcp tools
docker logs --tail 5 manna
```

Step 3 is the assumption the whole design rests on. `chroot` doesn't create a network
namespace, so a jailed process *should* reach host loopback — but that is reasoning, not
evidence, and it has not been tested. If it fails, MANNA needs a different transport and
much of this runbook changes. `curl` is present in the jail's `/usr/bin`, so the test
needs nothing installed.

Success on step 5 = **RA 202.4696, Dec +47.195** *and* a fresh `CallToolRequest` in the
container log. A confident answer with nothing in the log is the model guessing.

Do **not** use `claude mcp list` as a check — see Gotchas.

## Gotchas (hit on 2026-07-30/31)

- **IPv6 is disabled host-wide** (`disable_ipv6=1`, site policy — "we don't use IPv6
  here"). Anything resolving `localhost` gets `::1` and fails with errno 99. Use the
  `127.0.0.1` literal everywhere. This crashed `jupyter_server_mcp` on startup, which
  killed the single-user server, which surfaced as a 60s hub spawn timeout — three
  layers away from the cause.
- **PATH order silently downgrades node, and the symptom looks nothing like it.**
  `/data0/sw/anaconda3/bin` contains node **v18.16.0**. `claude` is a node script with a
  `#!/usr/bin/env node` shebang, so prepending that directory drops the interpreter below
  claude-code's `>=22`. The persona then **connects to MANNA, lists all 12 tools, and
  never calls one** — the chat just hangs, and MANNA's log shows a clean
  `ListToolsRequest` with no error, because from MANNA's side nothing is wrong. The only
  signal is the *absence* of a `CallToolRequest`. Hit on 2026-07-31 by prepending that
  path in the system config; fixed by removing it.
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
- **Cut a release tag.** The repo has never been tagged; the systemd unit above pins an
  image tag that doesn't exist yet.
- **Install the systemd unit on gp12.** It's specified above but not deployed — MANNA is
  currently an ad-hoc container in a user's home.
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
