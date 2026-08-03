# gp12 Deployment Runbook — MANNA via Jupyter AI

MANNA's VO tools in Astro Data Lab notebooks, via the Jupyter AI persona. MANNA runs as
**one container on host loopback**; every user's notebook server reaches it at
`http://127.0.0.1:8000/mcp/`.

**Status:** validated end-to-end on gp12 from **system config**, 2026-07-31. Persona
branded `@CosmicCoder`. The harness landed in the shared env 2026-08-03, so all users
should now have a persona — **pending confirmation by a second account**. Not yet
validated for a *jailed* user.

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
- **The checkout is `datalab`-owned**, to keep `/data0/sw` consistent. Update it as that
  account (`sudo su - datalab`, then `git pull`), and install as yourself — the scoped
  `sudo cp` grants belong to your own user, not `datalab`. Pulling as yourself leaves
  files owned by you and git refuses with "dubious ownership" until someone fixes it.
- Publishes to `127.0.0.1:8000` only. That's sufficient: user servers are local.
- **Does not need to be jail-visible** — users reach MANNA over the network, never its
  files. The opposite of §2.
- Upgrade: checkout the new tag, rebuild, edit `ExecStart`, `daemon-reload && restart`.

### 2. Persona harness — installed 2026-08-03

`claude` and `claude-agent-acp` are subprocesses the persona spawns, not services, so
they must be on the PATH of the user's server — inside the only tree bind-mounted into
the jail, `/data0/sw/anaconda3`. That env's node is **v18.16.0**; `claude-code` requires
**≥22**.

Preferred — upgrade in place, so the binaries land on a PATH that is already set up:

```bash
conda install -y -p /data0/sw/anaconda3 -c conda-forge 'nodejs>=22'
npm install -g --prefix /data0/sw/anaconda3 \
  @anthropic-ai/claude-code @agentclientprotocol/claude-agent-acp
```

Fallback if anything on gp12 still needs node 18 — side-by-side, fully reversible:

```bash
mkdir -p /data0/sw/anaconda3/opt && cd /data0/sw/anaconda3/opt
curl -fsSLO https://nodejs.org/dist/v22.11.0/node-v22.11.0-linux-x64.tar.xz
tar xf node-v22.11.0-linux-x64.tar.xz && mv node-v22.11.0-linux-x64 node22
/data0/sw/anaconda3/opt/node22/bin/npm install -g \
  --prefix /data0/sw/anaconda3/opt/node22 \
  @anthropic-ai/claude-code @agentclientprotocol/claude-agent-acp
```

- §3's `PATH` handles either shape; the side-by-side prefix wins when present.
- Use `npm install -g --prefix ...`, not `npm config set prefix` — the latter writes to
  the running admin's `~/.npmrc`, so the next admin silently installs elsewhere.
- The ACP adapter was **renamed** from `@zed-industries/claude-agent-acp` to
  `@agentclientprotocol/claude-agent-acp`. Both still provide the `claude-agent-acp`
  binary, which is what the persona gates on. npm may also require
  `--allow-scripts=@anthropic-ai/claude-code` for its postinstall step.
- **This is the gate on all-user access.** `claude.py` raises `PersonaRequirementsUnmet`
  at import when `claude-agent-acp` isn't on PATH, and the persona then **doesn't appear
  in the chat at all**. Confirmed 2026-07-31: a second user saw only `@file`.

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

It sets `c.MCPServer.host` (IPv6 fix), the `ANTHROPIC_*` model env, a `PATH` putting
node 22 ahead of the env's node 18, and `c.PersonaManager.builtin_mcp_servers`.

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

### 4. Per-user config, for every user

Both files users need are delivered by Claude Code's **managed policy** layer — one
root-owned directory, no per-user files, nothing written to NFS homes, and users cannot
override it:

```bash
cd /data0/sw/manna && git pull && cd deploy/gp12
sudo mkdir -p /etc/claude-code /home/jail/etc/claude-code
sudo cp claude-code/* /etc/claude-code/            # non-jailed staff accounts
sudo cp claude-code/* /home/jail/etc/claude-code/  # jailed Data Lab users
```

| File | Supplies | Without it |
|---|---|---|
| `managed-settings.json` | tool pre-approval | persona prompts on every call |
| `CLAUDE.md` | astronomy role framing | a generic coding assistant |

- **Both verified by A/B, 2026-08-02.** With the user's own `~/.claude` files removed,
  the policy copies still applied: the tool fired without prompting, and a sentinel
  instruction in the policy `CLAUDE.md` appeared in the reply.
- **Install to both, every time.** A chrooted process resolving `/etc` gets the jail's
  copy and cannot see the host's, so this is two filesystems rather than redundancy.
  Dropping the jail copy silently removes the config for every real user; dropping the
  host copy makes staff testing unrepresentative. Neither is NFS, so neither reaches
  gp13.
- This is why nothing needs `CLAUDE_CONFIG_DIR` or per-user seeding — and why the NFS
  `~/.claude.json` read-modify-write hazard isn't ours to solve.

### 5. Persona identity — optional, applied 2026-07-31

```bash
cd /data0/sw/manna && git pull && cd deploy/gp12
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

The role framing is separate and ships via §4; the rebrand is cosmetic.

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
- gp13 promotion — everything here must be ops-owned config, not hand edits

## Open questions for ADL ops

- Who owns the MANNA container long-term?
- Upgrade nodejs in `/data0/sw/anaconda3`, or install node ≥22 side-by-side?
- Is fixed port 3001 a real multi-user problem here — has gp13 seen it?
- Is `@CosmicCoder` the branding Data Lab wants? (Chadd's call, not ops.)
