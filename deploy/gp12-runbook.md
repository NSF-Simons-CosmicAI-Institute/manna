# gp12 Deployment Runbook — MANNA via Jupyter AI

MANNA's VO tools in Astro Data Lab notebooks, via the Jupyter AI persona. MANNA runs as
**one container on host loopback**; every user's notebook server reaches it at
`http://127.0.0.1:8000/mcp/`.

**Status:** validated end-to-end on gp12, including from a **jailed Data Lab account**
(2026-08-03). Persona branded `@datalab`, harness in the shared env, config from
system paths — nothing depends on any one user's home.

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

**Routine updates.** `/data0/sw/manna` is a `datalab`-owned checkout tracking `main`, so
every change is a pull as that account and an install as yourself (the scoped `sudo cp`
grants are per-user):

```bash
sudo su - datalab
cd /data0/sw/manna && git pull && exit
cd /data0/sw/manna/deploy/gp12
```

| Changed | Reinstall | Takes effect |
|---|---|---|
| MANNA server | rebuild image, `systemctl restart manna` | immediately |
| `jupyter_server_config.py` | §3 | next server spawn |
| `claude-code/*` | §4 | next server spawn |
| persona name/avatar | §5 (`./rebrand-persona.sh`) | next server spawn |

"Next server spawn" means each user must Stop/Start their own server from the Hub
Control Panel — a hub restart does not do it.

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
- **Deploy from `main` or a tag, never a feature branch.** The checkout on gp12 tracks
  whatever branch it was last set to; point it at the released line once this work
  merges (`sudo su - datalab`, then `git checkout main && git pull`).
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
the jail, `/data0/sw/anaconda3`. `claude-code` requires **node ≥22**; that env shipped
v18.16.0, and was upgraded to **v24.10.0** on 2026-08-03.

Done in place, so the binaries land on a PATH that is already set up:

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

One-time setup (root). The bind mount is what makes a single copy serve both jailed and
non-jailed accounts:

```bash
sudo mkdir -p /etc/claude-code /home/jail/etc/claude-code
sudo mount --bind /etc/claude-code /home/jail/etc/claude-code
# add the equivalent /etc/fstab line so it survives reboot
```

Then, to install or update:

```bash
cd /data0/sw/manna && git pull && cd deploy/gp12/claude-code
sudo cp CLAUDE.md /etc/claude-code/
sudo cp managed-settings.json /etc/claude-code/
```

| File | Supplies | Without it |
|---|---|---|
| `managed-settings.json` | tool pre-approval | persona prompts on every call |
| `CLAUDE.md` | astronomy role framing | a generic coding assistant |

- **Both verified by A/B, 2026-08-02.** With the user's own `~/.claude` files removed,
  the policy copies still applied: the tool fired without prompting, and a sentinel
  instruction in the policy `CLAUDE.md` appeared in the reply.
- **Why the bind mount.** A chrooted process resolving `/etc` gets the jail's copy and
  cannot see the host's — two filesystems, not redundancy. Without the mount you must
  install to both paths every time, and the persona wording churns often enough that they
  *will* drift. A symlink can't do this job: inside a chroot an absolute symlink target
  resolves against the jail root, so only the host→jail direction works, which would put
  system config under `/home/jail`. Neither path is NFS, so neither reaches gp13.
- Verify the mount is live before trusting a copy:
  `diff /etc/claude-code/CLAUDE.md /home/jail/etc/claude-code/CLAUDE.md`
- This is why nothing needs `CLAUDE_CONFIG_DIR` or per-user seeding — and why the NFS
  `~/.claude.json` read-modify-write hazard isn't ours to solve.

### 5. Persona identity — `@datalab`

```bash
cd /data0/sw/manna && git pull && cd deploy/gp12
./rebrand-persona.sh
rm -f ~/.jupyter/personas/datalab_persona.py
```

jupyter-ai 3.0.1 has no config knob for persona names, so the script renames the built-in
persona in site-packages. It needs only a scoped `sudo cp`, refuses to run if the
expected lines are absent, and backs up the original.

- **Reverts on any `pip install -U jupyter-ai-acp-client`.** Tell ops, or it will vanish
  during maintenance and be misdiagnosed.
- Alternative with no privileges at all: `gp12/personas/datalab_persona.py` in
  `~/.jupyter/personas/`. But local files only **add**, so the built-in persona stays
  alongside. The filename must contain **"persona"** or it's silently skipped.
- **The two are mutually exclusive** — do both and you get two `@datalab` personas.
- Persona ids are `jupyter-ai-personas::<module>::<ClassName>`, so `default_persona_id`
  differs between the routes.

The role framing is separate and ships via §4; the rebrand is cosmetic.

## Resolved

- **Node too old.** `/data0/sw/anaconda3` shipped v18.16.0 while `claude-code` requires
  ≥22, so the persona never registered for *anyone* — it hides itself when its adapter
  isn't on PATH. Ops upgraded the env to **v24.10.0** (2026-08-03). §3's PATH handling
  stays, since it also covers the side-by-side layout.
- **Jailed accounts.** Loopback crosses the chroot, the harness resolves on a jailed
  PATH, and the jail's `/etc/claude-code/` copy applies. All three confirmed 2026-08-03
  — they were the last assumptions the design rested on.

## Verify

Where each step runs matters — the `ANTHROPIC_*` env comes from the system config, so it
exists inside a spawned server and **not** in an SSH shell.

| # | Run from | Command | Pass |
|---|---|---|---|
| 1 | SSH | `curl -fsS http://127.0.0.1:8000/health` | `"version":"0.5.0"` |
| 2 | anywhere on loopback | `npx -y @modelcontextprotocol/inspector --cli http://127.0.0.1:8000/mcp --method tools/list` | 12 tools |
| 3 | **jailed user's terminal** | `curl -fsS http://127.0.0.1:8000/health` | reachable |
| 4 | **JupyterLab terminal** | `claude -p "say ok"` | `ok` |
| 5 | JupyterLab chat | `@datalab resolve galaxy m51 using MANNA mcp tools` | coords **+** log |

- **Step 3 was the assumption everything rested on** — confirmed 2026-08-03: `chroot`
  shares the host network namespace, so loopback crosses it. `curl` is already in the
  jail, so this test needs nothing installed. Re-run it after any change to how MANNA is
  published.
- **Step 5 passes only with both**: RA 202.4696 / Dec +47.195 **and** a fresh
  `CallToolRequest` in `docker logs manna`. A confident answer with nothing in the log is
  the model guessing.
- **Never use `claude mcp list`** — see Gotchas.

## Gotchas

Every one of these was hit during the rollout, and none announce themselves.

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
- **The persona can run shell commands as the user.** Claude Code's Bash tool is
  active — observed running `docker logs` unprompted. Not an escalation (every user has
  a JupyterLab terminal), but ops should know the assistant executes as the logged-in
  account, not a sandbox.
- **`jupyter_server_mcp` binds a fixed port — fixed in §3, don't undo it.** Its default
  is 3001, and under `LocalProcessSpawner` the first user to spawn wins that port while
  every other user's persona is still *pointed* at it — i.e. at someone else's notebook
  server. Seen on 2026-08-03: a second user's notebook tools all failed with permission
  errors from a server that wasn't theirs. §3 derives the port from `os.getuid()` so each
  user binds and connects to their own.

## Not done yet

- **Install the systemd unit** — MANNA is still a hand-started container, so a reboot
  takes the assistant's tools offline with no obvious cause. Needs root.
- **Cut a release tag** — the unit pins one that doesn't exist yet.
- **Two open server bugs** (fixed separately, not in this deployment):
  `vo_sia_search` raises on the waveband values its own schema documents; and SIA/cone
  results carry no `fetch_recipe`, so the assistant writes its own retrieval code
  instead of building on MANNA's.
- **gp13 promotion** — everything here must be ops-owned config, not hand edits.

## Open questions for ADL ops

- Who owns the MANNA container long-term, and when does the systemd unit go in?
- Is `@datalab` the branding Data Lab wants long-term?
