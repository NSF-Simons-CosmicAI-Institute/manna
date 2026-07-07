# Frontend single-user image: JupyterLab + Jupyter AI v3 + the Claude Code persona.
# Used two ways (see docker-compose.yml):
#   - `chat` mode: run directly as a single JupyterLab (AI chat panel, no Hub)
#   - `hub`  mode: spawned per-user by JupyterHub's DockerSpawner
#
# The MCP tool server is a SEPARATE compose service (`mcp`) reachable at
# http://mcp:8000/mcp/ on the compose network — this image does NOT colocate it.
# (For gp13 you may instead colocate it per the docs/examples/gp13/ image;
# here a shared service is simpler for local dev.)

ARG BASE_IMAGE=quay.io/jupyter/minimal-notebook:latest
FROM ${BASE_IMAGE}

# Jupyter AI v3 + Lab; jupyterhub provides `jupyterhub-singleuser` for hub mode.
USER ${NB_UID}
RUN pip install --no-cache-dir "jupyter-ai>=3" jupyterlab jupyterhub

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

# Persona credentials/model endpoint are injected at runtime (compose env_file),
# never baked: ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN / ANTHROPIC_DEFAULT_*_MODEL
# / CLAUDE_CODE_MAX_OUTPUT_TOKENS.
