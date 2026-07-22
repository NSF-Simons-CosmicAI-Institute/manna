# Reference single-user image for gp13: a Jupyter AI notebook server with the
# astro-archives MCP server colocated on loopback (Topology A in
# ../../deploy/gp13-runbook.md).
#
# BUILD FROM THIS DIRECTORY as the context — NOT the repo root:
#     docker build -t astro-archives-singleuser docs/examples/gp13/
# The repo-root .dockerignore excludes docs/ (and deploy/, tests/), so a
# repo-root context can't see the hook or config. Using this subdir as the
# context sidesteps that and picks up before-notebook.d/ + mcp_settings.json.
# (See build.sh / smoke-test.sh in this directory.)
#
# VALIDATION
#   2026-06-26 (minimal-notebook): package install, the before-notebook.d hook
#     launching the MCP server on loopback, writable astropy cache, tools
#     returning real data.
#   2026-06-29 (dlai01): the persona path itself — `claude mcp add --transport
#     http`, `claude mcp list` -> Connected, and a `claude -p` call invoking
#     vo_target_resolve live (M51 -> RA 202.47 / Dec +47.20). That proof was
#     rootless on the host; running it INSIDE this image is what smoke-test.sh
#     exercises.
#   STILL CONFIRM for gp13: the real base image (set BASE_IMAGE) and whether
#     $HOME is a persistent volume (the hook seeds config to survive that case).

ARG BASE_IMAGE=quay.io/jupyter/minimal-notebook:latest
FROM ${BASE_IMAGE}

# --- Python deps: this MCP server + Jupyter AI ---
USER ${NB_UID}
# Tracks the `dev` integration branch (0.4.0, stateless result-URL model). Pin to a
# release tag (e.g. @v0.4.0) once dev is promoted to main and tagged.
# jupyter-ai/acp-client are PINNED (not `>=3`) because the persona rebrand below
# patches the installed acp-client persona in place — see frontend.Dockerfile.
RUN pip install --no-cache-dir \
      "astro-archives-mcp @ git+https://github.com/dangause/astro-archives-mcp.git@dev" \
      "jupyter-ai==3.0.1" "jupyter-ai-acp-client==0.1.5" jupyterlab

# --- Node + the Claude persona's binaries ---
# The Jupyter AI "Claude" persona launches `claude-agent-acp`, which in turn
# wraps the `claude` CLI (@anthropic-ai/claude-code) for auth + model calls —
# BOTH must be on PATH. Skip this whole stage if backing the persona with a
# local model instead (see docs/local-model-backend.md).
USER root
RUN mamba install -y -c conda-forge nodejs && mamba clean -afy \
    && npm install -g @anthropic-ai/claude-code @zed-industries/claude-agent-acp

# --- Persona credentials (injected at spawn time — NEVER baked into the image) ---
# The persona needs Anthropic auth. The gp13 spawner must inject ONE of:
#   ANTHROPIC_API_KEY=...            # shared org key (simplest multi-user v1)
#   CLAUDE_CODE_OAUTH_TOKEN=...      # per-user long-lived token (`claude setup-token`)
# Optionally pin a config dir (e.g. a work account): CLAUDE_CONFIG_DIR=$HOME/.claude-work
# See "Persona credentials" in ../../deploy/gp13-runbook.md. The image ships no
# secret; this stage exists only to document the contract.

# --- Colocated MCP server: startup hook (loopback, writable cache) ---
# The hook also seeds mcp_settings.json at spawn time (see below), so config
# lands AFTER any persistent-$HOME volume is mounted rather than being shadowed.
COPY before-notebook.d/10-astro-archives-mcp.sh \
     /usr/local/bin/before-notebook.d/10-astro-archives-mcp.sh
RUN chmod +x /usr/local/bin/before-notebook.d/10-astro-archives-mcp.sh

# --- MCP config: staged outside $HOME; the hook copies it into ~/.jupyter ---
# Baking into /home/$NB_USER would be hidden by a mounted $HOME volume on gp13,
# so we stage it under /opt and let the startup hook place it every spawn.
COPY mcp_settings.json /opt/astro-archives/mcp_settings.json

# --- Rebrand the Claude Code ACP persona as `@CosmicCoder` (CosmicAI) ---
# Same override as deploy/frontend/frontend.Dockerfile: jupyter-ai 3.0.1 has no
# persona allow/disable knob and derives the `@`-handle from the persona's display
# name, so we patch `ClaudeAcpPersona.defaults` (name/description/avatar) in the
# pinned installed package. Engine/model/MCP behavior is unchanged. The grep guards
# fail the build if a version bump moves the patched lines.
USER ${NB_UID}
COPY CosmicCoder.png /tmp/CosmicCoder.png
RUN PKG_DIR=$(python -c "import jupyter_ai_acp_client, os; print(os.path.dirname(jupyter_ai_acp_client.__file__))") && \
    CLAUDE_PY="$PKG_DIR/acp_personas/claude.py" && \
    STATIC_DIR="$PKG_DIR/static" && \
    cp /tmp/CosmicCoder.png "$STATIC_DIR/CosmicCoder.png" && \
    sed -i 's/name="Claude"/name="CosmicCoder"/' "$CLAUDE_PY" && \
    sed -i 's#description="Claude Code as an ACP agent persona."#description="CosmicAI archive assistant — Claude Code with the astro-archives MCP tools."#' "$CLAUDE_PY" && \
    sed -i 's/"claude.svg"/"CosmicCoder.png"/' "$CLAUDE_PY" && \
    grep -q 'name="CosmicCoder"' "$CLAUDE_PY" && \
    grep -q 'CosmicCoder.png' "$CLAUDE_PY" && \
    test -f "$STATIC_DIR/CosmicCoder.png" && \
    rm /tmp/CosmicCoder.png && \
    echo "persona rebranded: @CosmicCoder"
