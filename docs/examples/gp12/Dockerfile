# Reference single-user image for gp12: a Jupyter AI notebook server with the
# MANNA MCP server colocated on loopback (Topology A in
# ../../deploy/gp12-runbook.md).
#
# BUILD FROM THIS DIRECTORY as the context — NOT the repo root (the repo-root
# .dockerignore excludes docs/, so a root context can't COPY the hook or config):
#     docker build -t manna-singleuser docs/examples/gp12/

ARG BASE_IMAGE=quay.io/jupyter/minimal-notebook:latest
FROM ${BASE_IMAGE}

# --- Python deps: this MCP server + Jupyter AI ---
USER ${NB_UID}
# Tracks the `dev` integration branch (0.5.0, stateless result-URL model). Pin to a
# release tag (e.g. @v0.5.0) once dev is promoted to main and tagged.
# jupyter-ai/acp-client are PINNED (not `>=3`) because the persona rebrand below
# patches the installed acp-client persona in place — see frontend.Dockerfile.
RUN pip install --no-cache-dir \
      "manna @ git+https://github.com/dangause/manna.git@dev" \
      "jupyter-ai==3.0.1" "jupyter-ai-acp-client==0.1.5" jupyterlab

# --- Node + the Claude persona's binaries ---
# The Jupyter AI "Claude" persona launches `claude-agent-acp`, which in turn
# wraps the `claude` CLI (@anthropic-ai/claude-code) for auth + model calls —
# BOTH must be on PATH. Skip this whole stage if backing the persona with a
# local model instead (see deploy/dlai01-vllm-runbook.md).
USER root
RUN mamba install -y -c conda-forge nodejs && mamba clean -afy \
    && npm install -g @anthropic-ai/claude-code @zed-industries/claude-agent-acp

# Persona credentials are injected at spawn time, never baked — see "Persona
# credentials" in ../../deploy/gp12-runbook.md.

# --- Colocated MCP server: startup hook (loopback, writable cache) ---
# The hook also seeds mcp_settings.json at spawn time (see below), so config
# lands AFTER any persistent-$HOME volume is mounted rather than being shadowed.
COPY before-notebook.d/10-manna.sh \
     /usr/local/bin/before-notebook.d/10-manna.sh
RUN chmod +x /usr/local/bin/before-notebook.d/10-manna.sh

# --- MCP config: staged outside $HOME; the hook copies it into ~/.jupyter ---
# Baking into /home/$NB_USER would be hidden by a mounted $HOME volume on gp12,
# so we stage it under /opt and let the startup hook place it every spawn.
COPY mcp_settings.json /opt/manna/mcp_settings.json

# --- Rebrand the ACP persona as `@CosmicCoder` ---
# Same patch as deploy/frontend/frontend.Dockerfile; see the note there.
USER ${NB_UID}
COPY CosmicCoder.png /tmp/CosmicCoder.png
RUN PKG_DIR=$(python -c "import jupyter_ai_acp_client, os; print(os.path.dirname(jupyter_ai_acp_client.__file__))") && \
    CLAUDE_PY="$PKG_DIR/acp_personas/claude.py" && \
    STATIC_DIR="$PKG_DIR/static" && \
    cp /tmp/CosmicCoder.png "$STATIC_DIR/CosmicCoder.png" && \
    sed -i 's/name="Claude"/name="CosmicCoder"/' "$CLAUDE_PY" && \
    sed -i 's#description="Claude Code as an ACP agent persona."#description="CosmicAI archive assistant — Claude Code with the MANNA MCP tools."#' "$CLAUDE_PY" && \
    sed -i 's/"claude.svg"/"CosmicCoder.png"/' "$CLAUDE_PY" && \
    grep -q 'name="CosmicCoder"' "$CLAUDE_PY" && \
    grep -q 'CosmicCoder.png' "$CLAUDE_PY" && \
    test -f "$STATIC_DIR/CosmicCoder.png" && \
    rm /tmp/CosmicCoder.png && \
    echo "persona rebranded: @CosmicCoder"
