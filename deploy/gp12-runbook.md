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

Three things. Only the first is ours to run as a service. The files themselves live in
**`gp12/`** next to this runbook — install them from the checkout rather than pasting
from here, so what's deployed can be diffed against what's in git.

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
>
> Interim, as deployed 2026-07-31 — pin the image to the commit so the running version
> is identifiable:
> ```bash
> cd /data0/sw/manna && SHA=$(git rev-parse --short HEAD)
> docker build -t manna:0.5.0-$SHA .        # e.g. manna:0.5.0-4f891d9
> ```
> Note `/data0/sw` is world-writable (777), so the clone needs no privileges — but the
> tree then belongs to whoever cloned it. Ops should chown it when installing the unit.

Run it as a systemd unit rather than an ad-hoc `docker run`, so it survives reboots and
no single user is a point of failure. The unit is **`gp12/manna.service`** — install it
rather than retyping it:

```bash
cd /data0/sw/manna/deploy/gp12
sudo cp manna.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now manna
curl -fsS http://127.0.0.1:8000/health          # {"status":"ok","version":"0.5.0",...}
```

Edit the image tag in the unit to match what you built. It publishes to
**`127.0.0.1:8000`** only — user servers are local processes on this host, so loopback
is sufficient and binding wider would expose the tools for no benefit.

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

The file is **`gp12/jupyter_server_config.py`**, kept in version control so it can
be reviewed and reinstalled rather than pasted. Install it from the checkout:

```bash
cd /data0/sw/manna && git pull && cd deploy/gp12
/data0/sw/anaconda3/bin/python -c "
from traitlets.config.loader import PyFileConfigLoader
cfg = PyFileConfigLoader('jupyter_server_config.py', path=['.']).load_config()
print('LOADED OK', sorted(cfg.keys()))"     # → ['MCPServer', 'PersonaManager']
sudo cp jupyter_server_config.py /data0/sw/anaconda3/etc/jupyter/
```

It sets four things: `c.MCPServer.host` (the IPv6 fix), the `ANTHROPIC_*` model env,
a `PATH` that deliberately does **not** prepend the anaconda prefix, and
`c.PersonaManager.builtin_mcp_servers`. Each carries a comment explaining why.

**`builtin_mcp_servers` is the delivery mechanism**, confirmed twice: 2026-07-30 with
the CLI-scope entry removed from `~/.claude.json`, and 2026-07-31 with the user's entire
`~/.jupyter/jupyter_server_config.py` moved aside. Nothing needs writing into users' NFS
homes.

> On gp12 this file can be installed without full root. Randy scoped a sudo rule to the
> exact command `cp jupyter_server_config.py /data0/sw/anaconda3/etc/jupyter/` — note it
> matches a **relative** filename, so run it from a directory holding a file by that
> name. No hub restart is needed; each single-user server reads this at spawn.
>
> **Always run the loader check first** — a bad config here breaks spawns for every
> account on the host. Use `PyFileConfigLoader` rather than `compile()`: `compile()` only
> parses, while the loader executes the file exactly as Jupyter does and shows the config
> it actually produces. That difference matters — `c = get_config()` parses fine but
> would `NameError` at load time if the loader didn't inject it.

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

**Where you run each step matters** — the `ANTHROPIC_*` env comes from the system Jupyter
config, so it exists inside a spawned server's process and *not* in an SSH shell. Running
step 4 from SSH fails with `Not logged in · Please run /login`, which is misleading: it
means Claude Code found no credential it recognizes, not that anyone needs to log in.

| # | Run from | Checks |
|---|---|---|
| 1 | SSH on gp12 | service is up |
| 2 | anywhere that reaches loopback | MCP protocol + tool count |
| 3 | **a jailed user's terminal** | loopback crosses the chroot |
| 4 | **a JupyterLab terminal** | model path |
| 5 | JupyterLab chat | end-to-end |

```bash
# 1. Service up
curl -fsS http://127.0.0.1:8000/health

# 2. Protocol + tools
npx -y @modelcontextprotocol/inspector --cli http://127.0.0.1:8000/mcp --method tools/list
# → 12 tools: vo_archive_list, vo_tap_query, vo_target_resolve, …

# 3. Loopback reaches the jail
curl -fsS http://127.0.0.1:8000/health

# 4. Harness — model path only. MUST be a JupyterLab terminal, not SSH.
claude -p "say ok"          # → ok

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
- **"Not logged in · Please run /login" means missing env, not missing credentials.**
  Claude Code prints it whenever it can't find a credential *it* recognizes — including
  when `ANTHROPIC_BASE_URL` / `ANTHROPIC_API_KEY` simply aren't set, as in an SSH shell
  where the Jupyter config's `os.environ` block never ran. Nobody needs to log in.
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
- **Persona identity — `@CosmicCoder`.** Two routes, and they differ in reach:
  - *Per-user, no privileges*: drop `gp12/personas/cosmiccoder_persona.py` into
    `~/.jupyter/personas/`. But local files only **add** — the stock `@Claude` stays, so
    you get both handles. **The filename must contain "persona"**: `find_persona_files`
    globs only `*.py` whose stem matches that, so `cosmiccoder.py` is silently skipped —
    never imported, nothing logged, persona simply absent.
  - *All users*: patch `name`/`description`/avatar in `jupyter_ai_acp_client`
    (`frontend/frontend.Dockerfile` has the exact sed lines, and the three targets are
    confirmed present in gp12's copy). Needs write access to the shared env and reverts
    on any package upgrade. It also changes what every account sees, which is a Data Lab
    product decision rather than an ops one.

  The astronomy role framing is separate and independent — `frontend/CLAUDE.md` copied to
  `~/.claude/CLAUDE.md`. That is the half that changes answer quality; the rebrand is
  cosmetic.
- **gp13 promotion.** gp13 is production; gp12 is the sandbox. Everything here should be
  reproducible as ops-owned config, not hand edits.

## Open questions for ADL ops

- Who owns the MANNA container long-term, and where should it be defined as a service?
- Upgrade nodejs in `/data0/sw/anaconda3`, or install node ≥22 side-by-side?
- Is the fixed port 3001 a real multi-user problem here, and has gp13 seen it?
- Should the persona be rebranded for Data Lab users, and whose call is that?
