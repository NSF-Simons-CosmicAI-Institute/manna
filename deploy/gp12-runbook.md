# gp12 Deployment Runbook — MANNA via Jupyter AI

MANNA's VO tools in Astro Data Lab notebooks, via the Jupyter AI persona. MANNA runs as
**one container on host loopback**; every user's notebook server reaches it at
`http://127.0.0.1:8000/mcp/`.

**Status:** validated end-to-end on gp12 from **system config**, 2026-07-31. Persona
branded `@CosmicCoder`. Not yet validated for a *jailed* user — see Blockers.

> **Proof.** Chat → `resolve galaxy m51 using MANNA mcp tools` →
> `✓ mcp__manna__vo_target_resolve` → RA 202.469575°, Dec +47.19525833° (ICRS), with a
> matching `CallToolRequest` in the container log.

## What gp12 is

gp12 runs **its own JupyterHub** — we deploy no hub and install no Python packages.

| | |
|---|---|
| Hub | JupyterHub 4.0.2 from `/data0/sw/anaconda3`, config `/root/ssl.jupyterhub_config.py` |
| Public | `configurable-http-proxy` on **:443**, `gp12.datalab.noirlab.edu` |
| Spawner | **`LocalProcessSpawner`** — user servers are host processes |
| Auth | `dlauthenticator.DataLabAuthenticator` |
| Users | `/home/jail/dlusers` (NFS, ~5100), chrooted to `/home/jail` |
| Stack | Python 3.10.13, JupyterLab 4.1.5, **jupyter-ai 3.0.1 already installed** |

Because the spawner is local, **loopback is shared** — no container networking, no
service discovery, no off-host exposure.

```
gp12 JupyterHub (:443) ──spawns──► user server (Jupyter AI persona)
                                        │                │
                              MCP tools │                │ model
                                        ▼                ▼
                            MANNA container        dlai01 vLLM
                            127.0.0.1:8000         dlai01.csdc.noirlab.edu:8002
```

## Deploy

Files live in **`gp12/`** next to this runbook. Install from the checkout, not by pasting
— then what's deployed can be diffed against git.

### 1. MANNA container

```bash
git clone https://github.com/dangause/manna.git /data0/sw/manna
cd /data0/sw/manna && git checkout v0.5.0
docker build -t manna:v0.5.0 .
cd deploy/gp12 && sudo cp manna.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now manna
curl -fsS http://127.0.0.1:8000/health
```

- **No release tag exists yet.** Cut one from `main`, or pin a commit
  (`docker build -t manna:0.5.0-$(git rev-parse --short HEAD) .`). Never deploy from
  `dev` — the deployed version would change on every rebuild.
- `/data0/sw` is world-writable, so the clone needs no privileges — but it belongs to
  whoever cloned it. Ops should `chown` it.
- Publishes to `127.0.0.1:8000` only. That's sufficient: user servers are local.
- **Does not need to be jail-visible** — users reach MANNA over the network, never its
  files. The opposite of §2.
- Upgrade: checkout the new tag, rebuild, edit `ExecStart`, `daemon-reload && restart`.

### 2. Persona harness — **BLOCKED**

`claude` and `claude-agent-acp` are subprocesses the persona spawns, not services, so
they must be executable from the user's server — which means the only tree bind-mounted
into the jail:

```bash
npm config set prefix /data0/sw/anaconda3
npm install -g @anthropic-ai/claude-code @zed-industries/claude-agent-acp
```

Requires **node ≥ 22**; that prefix has v18.16.0. See Blockers.

### 3. System Jupyter config

Install `gp12/jupyter_server_config.py` to
`/data0/sw/anaconda3/etc/jupyter/jupyter_server_config.py`:

```bash
cd /data0/sw/manna && git pull && cd deploy/gp12
/data0/sw/anaconda3/bin/python -c "
from traitlets.config.loader import PyFileConfigLoader
cfg = PyFileConfigLoader('jupyter_server_config.py', path=['.']).load_config()
print('LOADED OK', sorted(cfg.keys()))"     # → ['MCPServer', 'PersonaManager']
sudo cp jupyter_server_config.py /data0/sw/anaconda3/etc/jupyter/
```

It sets `c.MCPServer.host` (IPv6 fix), the `ANTHROPIC_*` model env, a `PATH` that
deliberately excludes the anaconda prefix, and `c.PersonaManager.builtin_mcp_servers`.

- **`builtin_mcp_servers` is the delivery mechanism.** Confirmed by removing the user's
  own config entirely and seeing the tools survive — so nothing needs writing into NFS
  homes.
- Must be a `.py` in that directory, **not** in `jupyter_server_config.d/` (JSON
  extension toggles only). It's a *Jupyter Server* setting; in the JupyterHub config it
  does nothing.
- No hub restart needed — each server reads it at spawn.
- **Always run the loader check**, not `compile()`. A bad config breaks spawns for every
  account; `compile()` only parses, so it passes files that raise at load time.
- The scoped `sudo cp` grant matches a **relative** filename — hence the `cd`.

### 4. Persona identity — optional, applied 2026-07-31

```bash
cd /data0/sw/manna/deploy/gp12
./rebrand-persona.sh
rm -f ~/.jupyter/personas/cosmiccoder_persona.py
```

jupyter-ai 3.0.1 has no config knob for persona names, so the script renames the built-in
persona in site-packages. It needs only a scoped `sudo cp`, refuses to run if the
expected lines are absent, and backs up the original.

- **Reverts on any `pip install -U jupyter-ai-acp-client`.** Tell ops, or it will vanish
  during maintenance and be misdiagnosed.
- Alternative with no privileges at all: `gp12/personas/cosmiccoder_persona.py` in
  `~/.jupyter/personas/`. But local files only **add** — `@Claude` stays alongside. The
  filename must contain **"persona"** or it's silently skipped.
- **The two are mutually exclusive** — do both and you get two `@CosmicCoder`s.
- Persona ids are `jupyter-ai-personas::<module>::<ClassName>`, so `default_persona_id`
  differs between the routes.

Separately, `frontend/CLAUDE.md` → `~/.claude/CLAUDE.md` gives the astronomy role
framing. That's the half that changes answer quality; the rebrand is cosmetic.

## Blockers

**Node is too old in the jail.** `claude-code` 2.1.220 requires `node >=22`:

| Path | Version | In jail? |
|---|---|---|
| `/usr/bin/node` | v26.5.0 | **no** — jail's `/usr/bin` is curated |
| `/data0/sw/anaconda3/bin/node` | **v18.16.0** | yes |

Fix by upgrading nodejs in the anaconda env, or installing node ≥22 side-by-side and
prepending it to `PATH`. Upgrading in place removes the PATH-ordering footgun entirely.

**All validation used a staff account** (`dgause`, local home, host node) — not a jailed
`dlusers` account. A second round inside the jail is required.

## Verify

Where each step runs matters — the `ANTHROPIC_*` env comes from the system config, so it
exists inside a spawned server and **not** in an SSH shell.

| # | Run from | Command | Pass |
|---|---|---|---|
| 1 | SSH | `curl -fsS http://127.0.0.1:8000/health` | `"version":"0.5.0"` |
| 2 | anywhere on loopback | `npx -y @modelcontextprotocol/inspector --cli http://127.0.0.1:8000/mcp --method tools/list` | 12 tools |
| 3 | **jailed user's terminal** | `curl -fsS http://127.0.0.1:8000/health` | reachable |
| 4 | **JupyterLab terminal** | `claude -p "say ok"` | `ok` |
| 5 | JupyterLab chat | `@CosmicCoder resolve galaxy m51 using MANNA mcp tools` | coords **+** log |

- **Step 3 is the assumption everything rests on** and is untested. `chroot` shares the
  host network namespace, so it *should* work — but that's reasoning, not evidence. If it
  fails, MANNA needs a different transport. `curl` is already in the jail.
- **Step 5 passes only with both**: RA 202.4696 / Dec +47.195 **and** a fresh
  `CallToolRequest` in `docker logs manna`. A confident answer with nothing in the log is
  the model guessing.
- **Never use `claude mcp list`** — see Gotchas.

## Gotchas

Every one of these was hit on 2026-07-30/31, and none announce themselves.

- **IPv6 is disabled host-wide** (site policy). Anything resolving `localhost` gets `::1`
  and fails with errno 99 — use the `127.0.0.1` literal everywhere. This killed
  `jupyter_server_mcp`, which killed the single-user server, which surfaced as a 60s hub
  spawn timeout: three layers from the cause.
- **PATH order silently downgrades node.** Prepending `/data0/sw/anaconda3/bin` drops
  `claude` to node 18. The persona then connects, lists all 12 tools, and **never calls
  one** — no error anywhere, because nothing is wrong from MANNA's side. The only signal
  is the *absence* of a `CallToolRequest`.
- **`builtin_mcp_servers`' default URL uses `localhost`** — dead on this host. Setting
  the trait replaces the default, so restate the Jupyter MCP Server entry with an IPv4
  literal or you lose it.
- **`claude mcp list` lies, twice over.** It reads the CLI's config, not the persona's,
  and it reported `ConnectionRefused` against a server that was serving fine. The
  container log is the only trustworthy signal.
- **A healthy container can have a dead port binding.** Killing host processes can take
  out `docker-proxy` while `docker ps` still shows `Up (healthy)`. `docker restart`
  recreates it; `docker start` on a running container is a no-op.
- **"Not logged in · Please run /login" means missing env, not missing credentials** —
  typically running `claude` from SSH, where the config's `os.environ` never ran.
- **Silent persona? Check identity first.** A duplicate-UID account had the hub spawning
  as one user while the shell was another, so no per-user config was read and the chat
  sat mute. Run `whoami; echo $HOME` *inside the spawned server*.
- **`jupyter_server_mcp` binds a fixed port 3001.** With `LocalProcessSpawner` concurrent
  users may collide. Untested. MANNA doesn't need that extension — disabling it removes
  this and the IPv6 problem together.

## Not done yet

- Jailed-user validation (blocked on node ≥ 22)
- Cut a release tag — the systemd unit pins one that doesn't exist
- Install the systemd unit; MANNA is currently an ad-hoc container
- Port 3001 concurrency
- **Per-user Claude config for ~5,100 users.** `~/.claude/settings.json` (tool
  pre-approval — without it the persona prompts on every call) and `~/.claude/CLAUDE.md`
  both live in user homes with no system-wide equivalent. Unverified candidates: Claude
  Code managed settings, or a shared `CLAUDE_CONFIG_DIR`.
- gp13 promotion — everything here must be ops-owned config, not hand edits

## Open questions for ADL ops

- Who owns the MANNA container long-term?
- Upgrade nodejs in `/data0/sw/anaconda3`, or install node ≥22 side-by-side?
- Is fixed port 3001 a real multi-user problem here — has gp13 seen it?
- Is `@CosmicCoder` the branding Data Lab wants? (Chadd's call, not ops.)
