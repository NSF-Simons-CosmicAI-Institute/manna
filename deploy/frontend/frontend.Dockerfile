# Frontend single-user image: JupyterLab + Jupyter AI v3 + the CosmicCoder persona.
# Two modes (see docker-compose.yml): `chat` runs it standalone; `hub` has
# JupyterHub's DockerSpawner launch one per user. The MCP server is a separate
# compose service at http://mcp:8000/mcp/ — this image does not colocate it.
# (docs/examples/gp12/ has the colocated variant.)

ARG BASE_IMAGE=quay.io/jupyter/minimal-notebook:latest
FROM ${BASE_IMAGE}

# Jupyter AI v3 + Lab; jupyterhub provides `jupyterhub-singleuser` for hub mode.
# Versions are PINNED (not `>=3`) because the persona rebrand below patches the
# installed `jupyter_ai_acp_client` persona in place — a floating install could
# shift the file the patch targets. Bump these deliberately + re-verify the patch.
USER ${NB_UID}
RUN pip install --no-cache-dir \
    "jupyter-ai==3.0.1" "jupyter-ai-acp-client==0.1.5" jupyterlab jupyterhub

# Core scientific + IVOA/VO stack, so every spawned notebook has a standard
# archive workflow ready off the bat. The minimal-notebook base ships WITHOUT
# numpy/pandas/scipy/matplotlib (that's scipy-notebook), so install them here
# alongside the astronomy libs (astropy, pyvo).
RUN pip install --no-cache-dir \
    numpy pandas scipy matplotlib astropy pyvo

# Node + the persona binaries: claude-agent-acp wraps the `claude` CLI, need both.
USER root
RUN mamba install -y -c conda-forge nodejs && mamba clean -afy \
    && npm install -g @anthropic-ai/claude-code @zed-industries/claude-agent-acp

# Seed the MCP config where Jupyter AI resolves it (JupyterLab root = $HOME).
# Points at the shared `mcp` service, not loopback.
USER ${NB_UID}
COPY --chown=${NB_UID}:${NB_GID} mcp_settings.json /home/${NB_USER}/.jupyter/mcp_settings.json

# Pre-allow all astro-archives MCP tools so the persona runs them without a per-call
# permission prompt (Claude Code reads permissions.allow from ~/.claude/settings.json).
COPY --chown=${NB_UID}:${NB_GID} claude_settings.json /home/${NB_USER}/.claude/settings.json

# Concise-output + astronomy role framing. Claude Code loads ~/.claude/CLAUDE.md
# as user-scope context.
COPY --chown=${NB_UID}:${NB_GID} CLAUDE.md /home/${NB_USER}/.claude/CLAUDE.md

# Rebrand the ACP persona as `@CosmicCoder`. jupyter-ai 3.0.1 has no persona
# disable knob and derives the `@`-handle from the display name, so we patch
# `ClaudeAcpPersona.defaults` in the installed package. The grep guards fail the
# build if a version bump moves the patched lines.
# See docs/jupyter-ai-integration.md "Renaming the persona".
COPY --chown=${NB_UID}:${NB_GID} CosmicCoder.png /tmp/CosmicCoder.png
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

# Persona credentials/model endpoint are injected at runtime (compose env_file),
# never baked: ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN / ANTHROPIC_DEFAULT_*_MODEL
# / CLAUDE_CODE_MAX_OUTPUT_TOKENS.
