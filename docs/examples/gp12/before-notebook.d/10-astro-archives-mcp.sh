#!/usr/bin/env bash
# jupyter/docker-stacks start hook: launch the colocated astro-archives MCP
# server on loopback before the single-user JupyterLab starts.
#
# Install: copy to /usr/local/bin/before-notebook.d/ in the single-user image.
# docker-stacks *sources* these files, so we background the server (never block
# startup) and make the launch idempotent (safe if the hook runs more than once).
#
# Also seeds ~/.jupyter/mcp_settings.json from the image-staged copy under /opt,
# pointing the Jupyter AI persona at http://127.0.0.1:8000/mcp/. Seeding here
# (rather than baking into the image's $HOME) means the config survives a
# persistent-$HOME volume mount, which would otherwise shadow a baked-in file.

ASTRO_MCP_PORT="${ASTRO_MCP_PORT:-8000}"

# Seed the MCP config into the dir Jupyter AI resolves (~/.jupyter). Authoritative
# refresh each spawn so the deployment's URL can't drift; staged file is read-only.
ASTRO_MCP_CFG_SRC="${ASTRO_MCP_CFG_SRC:-/opt/astro-archives/mcp_settings.json}"
if [ -f "$ASTRO_MCP_CFG_SRC" ]; then
    mkdir -p "$HOME/.jupyter"
    cp -f "$ASTRO_MCP_CFG_SRC" "$HOME/.jupyter/mcp_settings.json"
fi

# Astropy/pyvo MUST have writable scratch for their caches, or every
# vo_target_resolve / vo_registry_search returns archive_error. Keep these on the
# user's (writable) home volume.
export TMPDIR="${TMPDIR:-$HOME/.cache/tmp}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"
mkdir -p "$TMPDIR" "$XDG_CACHE_HOME"

# Health probe via python (always present in a Jupyter image; minimal-notebook
# has no curl) so this hook is base-image-agnostic.
if python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${ASTRO_MCP_PORT}/health', timeout=2)" >/dev/null 2>&1; then
    echo "[astro-archives-mcp] already running on :${ASTRO_MCP_PORT}"
else
    echo "[astro-archives-mcp] starting on 127.0.0.1:${ASTRO_MCP_PORT}"
    STABLE_HOST=127.0.0.1 STABLE_PORT="${ASTRO_MCP_PORT}" STABLE_DEPLOYMENT=adl \
        nohup python -m astro_archives_mcp \
        >"$HOME/.astro-archives-mcp.log" 2>&1 &
fi
