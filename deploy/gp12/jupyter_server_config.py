"""System Jupyter Server config for gp12 — MANNA / Jupyter AI persona.

Install to /data0/sw/anaconda3/etc/jupyter/jupyter_server_config.py. Read by every
single-user server at spawn, so no hub restart is needed — but a syntax error here
breaks spawns for every account on the host. Always compile-check first:

    cd /data0/sw/manna/deploy/gp12
    /data0/sw/anaconda3/bin/python -c "compile(open('jupyter_server_config.py').read(),'c','exec')"
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

# The persona spawns `claude-agent-acp`, which must be on PATH.
#
# Do NOT prepend /data0/sw/anaconda3/bin: its node is v18.16.0, `claude` is a node
# script resolved via `#!/usr/bin/env node`, and claude-code requires >=22. Putting
# it first silently downgrades the interpreter — the persona then connects to MANNA,
# lists all 12 tools, and never calls one, with no error anywhere.
#
# Once ops installs node >=22, that bin dir must come BEFORE the anaconda prefix,
# and the per-user entry below can be dropped.
os.environ["PATH"] = ":".join(
    [
        os.path.join(os.path.expanduser("~"), ".npm-global/bin"),  # transitional
        os.environ.get("PATH", "/usr/bin:/bin"),
    ]
)

# MCP servers handed to the persona. Setting this REPLACES the default, whose URL is
# built as http://localhost:{port}/mcp and is therefore dead on this host — so the
# Jupyter MCP Server entry has to be restated here with an IPv4 literal.
c.PersonaManager.builtin_mcp_servers = [
    {"type": "http", "name": "manna", "url": "http://127.0.0.1:8000/mcp/", "headers": []},
    {
        "type": "http",
        "name": "Jupyter MCP Server",
        "url": "http://127.0.0.1:3001/mcp",
        "headers": [],
    },
]
