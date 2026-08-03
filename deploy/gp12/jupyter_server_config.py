"""System Jupyter Server config for gp12 — MANNA / Jupyter AI persona.

Install to /data0/sw/anaconda3/etc/jupyter/jupyter_server_config.py. Read by every
single-user server at spawn, so no hub restart is needed — but a syntax error here
breaks spawns for every account on the host. Always run the loader check first — it
executes this file the way Jupyter does, unlike compile(), which only parses:

    cd /data0/sw/manna/deploy/gp12
    /data0/sw/anaconda3/bin/python -c "
    from traitlets.config.loader import PyFileConfigLoader
    cfg = PyFileConfigLoader('jupyter_server_config.py', path=['.']).load_config()
    print('LOADED OK', sorted(cfg.keys()))"
    sudo cp jupyter_server_config.py /data0/sw/anaconda3/etc/jupyter/

See ../gp12-runbook.md for the full procedure and the gotchas behind each setting.
Validated end-to-end on gp12 2026-07-31.
"""

import os

c = get_config()  # noqa: F821  (injected by jupyter_server)

# IPv6 is disabled host-wide on gp12 (site policy), so `localhost` resolves to ::1
# and binds fail with errno 99. Without this, jupyter_server_mcp dies on startup,
# which kills the single-user server, which surfaces as a 60s hub spawn timeout.
c.MCPServer.host = "127.0.0.1"

# Model backend: dlai01 vLLM, reached directly over the ADL network. No proxy, and
# the server is keyless — ANTHROPIC_API_KEY exists only to satisfy Claude Code's own
# login-state check, which otherwise reports "Not logged in · Please run /login".
os.environ.setdefault("ANTHROPIC_BASE_URL", "http://dlai01.csdc.noirlab.edu:8002")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
os.environ.setdefault("ANTHROPIC_DEFAULT_OPUS_MODEL", "openai/gpt-oss-120b")
os.environ.setdefault("ANTHROPIC_DEFAULT_SONNET_MODEL", "openai/gpt-oss-120b")
os.environ.setdefault("ANTHROPIC_DEFAULT_HAIKU_MODEL", "openai/gpt-oss-120b")

# Output cap + early auto-compaction. Behind ANTHROPIC_BASE_URL Claude Code can't
# detect the real context window and assumes ~200K, so it never compacts before the
# true 131072 wall and long chats overflow.
os.environ.setdefault("CLAUDE_CODE_MAX_OUTPUT_TOKENS", "4096")
os.environ.setdefault("CLAUDE_CODE_MAX_CONTEXT_TOKENS", "131072")
os.environ.setdefault("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "120000")
os.environ.setdefault("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE", "85")

# The Claude Agent SDK makes background calls to the real api.anthropic.com, which
# 401 against a local backend and get surfaced as "not authenticated" mid-session.
os.environ.setdefault("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")

# The persona spawns `claude-agent-acp`, which must be on PATH — and `claude` is a
# node script resolved via `#!/usr/bin/env node`, so whichever node comes first on
# PATH is the interpreter it runs under. claude-code requires node >=22; if node 18
# wins, the persona connects to MANNA, lists all 12 tools, and never calls one, with
# no error anywhere.
#
# Handles either install shape: node >=22 upgraded in place (binaries land in the
# env's own bin), or installed side-by-side under opt/node22. The side-by-side path
# comes first so it wins when both exist.
_prefixes = [
    p for p in ("/data0/sw/anaconda3/opt/node22/bin", "/data0/sw/anaconda3/bin") if os.path.isdir(p)
]
os.environ["PATH"] = ":".join(_prefixes + [os.environ.get("PATH", "/usr/bin:/bin")])

# jupyter_server_mcp binds a FIXED port (default 3001) inside each single-user server.
# Under LocalProcessSpawner every user's server shares one host, so the first to spawn
# wins 3001 and everyone else's extension fails to bind — while still being pointed at
# that port, i.e. at another user's notebook server. Observed 2026-08-03: a second user's
# persona got permission errors from a server that wasn't theirs.
#
# Derive a per-user port instead. This file runs inside each user's own process, so
# os.getuid() is theirs, and the same value feeds both the bind and the URL handed to
# the persona.
_mcp_port = 20000 + (os.getuid() % 40000)
c.MCPExtensionApp.mcp_port = _mcp_port

# MCP servers handed to the persona. Setting this REPLACES the default, whose URL is
# built as http://localhost:{port}/mcp and is therefore dead on this host (IPv6 off).
c.PersonaManager.builtin_mcp_servers = [
    {"type": "http", "name": "manna", "url": "http://127.0.0.1:8000/mcp/", "headers": []},
    {
        "type": "http",
        "name": "Jupyter MCP Server",
        "url": f"http://127.0.0.1:{_mcp_port}/mcp",
        "headers": [],
    },
]
