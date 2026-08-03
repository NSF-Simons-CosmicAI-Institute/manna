# gp12 deployment artifacts

The files ops installs on gp12. **`../gp12-runbook.md` is the procedure** — this
directory is just the things it tells you to copy, kept in version control so they
can be reviewed, diffed, and reinstalled rather than pasted from a document.

| File | Installs to | Needs |
|---|---|---|
| `jupyter_server_config.py` | `/data0/sw/anaconda3/etc/jupyter/` | scoped `sudo cp` |
| `manna.service` | `/etc/systemd/system/` | root |
| `personas/datalab_persona.py` | `~/.jupyter/personas/` | nothing (per-user) |
| `claude-code/` (2 files) | `/etc/claude-code/` **and** `/home/jail/etc/claude-code/` | root |
| `rebrand-persona.sh` | patches installed `jupyter_ai_acp_client` | scoped `sudo cp` |

`/data0/sw/manna` is a git checkout on gp12, so the deploy loop is a pull and a copy. It
should track **`main` or a tag** — not a feature branch — once this work has merged:

```bash
sudo su - datalab -c 'cd /data0/sw/manna && git pull'   # checkout is datalab-owned
cd /data0/sw/manna/deploy/gp12
/data0/sw/anaconda3/bin/python -c "
from traitlets.config.loader import PyFileConfigLoader
cfg = PyFileConfigLoader('jupyter_server_config.py', path=['.']).load_config()
print('LOADED OK', sorted(cfg.keys()))"     # → ['MCPServer', 'PersonaManager']
sudo cp jupyter_server_config.py /data0/sw/anaconda3/etc/jupyter/
```

The `sudo` grant matches a **relative** filename, which is why the `cd` matters. No hub
restart is needed — each single-user server reads that config at spawn — but a bad config
breaks spawns for every account, hence the loader check. It executes the file the way
Jupyter does and prints the config produced, which `compile()` cannot: `compile()` only
parses, so it would pass a file that raises at load time.

## `claude-code/` goes to two places

```bash
sudo mkdir -p /etc/claude-code /home/jail/etc/claude-code
sudo cp claude-code/* /etc/claude-code/            # non-jailed staff accounts
sudo cp claude-code/* /home/jail/etc/claude-code/  # jailed Data Lab users
```

Not redundancy — a chrooted process resolving `/etc` gets the jail's copy and cannot
see the host's. **Install to both, every time**; dropping the jail copy silently
removes the config for all ~5,100 real users, and dropping the host copy makes your own
testing unrepresentative of theirs.

Claude Code's managed-policy layer loads these in every session regardless of working
directory, and users cannot override them — which is why nothing here needs writing into
user homes.

## Not here

- **The persona rename** is the same technique as `../frontend/frontend.Dockerfile`
  (which brands the local dev stack `@CosmicCoder`); `rebrand-persona.sh` here applies it
  to a bare-metal install as **`@datalab`**. `personas/datalab_persona.py` is the
  per-user alternative needing no privileges — it *adds* the persona rather than
  replacing the stock `@Claude`.
- `claude-code/CLAUDE.md` and `../frontend/CLAUDE.md` **deliberately differ in branding**:
  gp12 is a Data Lab product, the local dev stack is the CosmicAI prototype. Keep the
  response-style guidance in step; let the naming diverge.
