# gp12 deployment artifacts

The files ops installs on gp12. **`../gp12-runbook.md` is the procedure** — this
directory is just the things it tells you to copy, kept in version control so they
can be reviewed, diffed, and reinstalled rather than pasted from a document.

| File | Installs to | Needs |
|---|---|---|
| `jupyter_server_config.py` | `/data0/sw/anaconda3/etc/jupyter/` | scoped `sudo cp` |
| `manna.service` | `/etc/systemd/system/` | root |
| `personas/cosmiccoder_persona.py` | `~/.jupyter/personas/` | nothing (per-user) |
| `managed-settings.json` | `/etc/claude-code/` | root |
| `rebrand-persona.sh` | patches installed `jupyter_ai_acp_client` | scoped `sudo cp` |

`/data0/sw/manna` is a git checkout on gp12, so the deploy loop is a pull and a copy:

```bash
cd /data0/sw/manna && git pull
cd deploy/gp12
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

## Not here

- **`CLAUDE.md`** (persona role/style) and **`claude_settings.json`** (tool
  pre-approval) live in `../frontend/`, shared with the local dev stack. Both are
  per-user files under `~/.claude/`, and delivering them to ~5,100 users is an open
  problem — see the runbook.
- **The `@CosmicCoder` site-packages patch** lives in `../frontend/frontend.Dockerfile`.
  `personas/cosmiccoder_persona.py` here is the per-user alternative that needs no privileges;
  it *adds* the persona rather than replacing the stock `@Claude`.
