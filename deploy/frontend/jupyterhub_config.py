# JupyterHub config for local `hub` mode — DockerSpawner launches the frontend
# image per user, on the same compose network as the `mcp` service.
import os

c = get_config()  # noqa: F821  (injected by jupyterhub)

# --- Spawner: one frontend container per user -------------------------------
c.JupyterHub.spawner_class = "dockerspawner.DockerSpawner"
c.DockerSpawner.image = os.environ.get("FRONTEND_IMAGE", "astro-frontend:dev")

# Spawned single-user containers must join the compose network so they can
# resolve the `mcp` service and reach the hub. Must match the compose network.
c.DockerSpawner.network_name = os.environ.get("DOCKER_NETWORK", "frontend_default")
c.DockerSpawner.remove = True  # clean up stopped user containers

# The hub must be reachable from spawned containers by its service name.
c.JupyterHub.hub_ip = "0.0.0.0"
c.JupyterHub.hub_connect_ip = os.environ.get("HUB_SERVICE_NAME", "hub")

# Inject the model endpoint + persona config into every spawned container.
c.DockerSpawner.environment = {
    k: os.environ[k]
    for k in (
        # persona auth — one of these must be forwarded or the spawned persona has no
        # Claude credentials. Hosted: OAUTH_TOKEN or API_KEY. dlai01 vLLM via the datalab
        # proxy: ANTHROPIC_CUSTOM_HEADERS carries the Basic-auth header (and AUTH_TOKEN
        # must stay UNSET — a Bearer header collides with it → nginx 401; see .env.example).
        "CLAUDE_CODE_OAUTH_TOKEN",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_CUSTOM_HEADERS",
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS",
        # Context-window / auto-compaction (runbook Gotcha 4). Behind ANTHROPIC_BASE_URL
        # Claude Code can't see the model's real window and assumes ~200K, so it never
        # compacts before the true 131072 wall → vLLM 500 (mislabeled "not authenticated").
        # MAX_CONTEXT_TOKENS tells it the truth; the WINDOW/PCT knobs make it compact early
        # so a long chat auto-summarizes and continues instead of erroring.
        "CLAUDE_CODE_MAX_CONTEXT_TOKENS",
        "CLAUDE_CODE_AUTO_COMPACT_WINDOW",
        "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE",
    )
    if os.environ.get(k)
}

# The Claude Agent SDK (behind the @claude ACP persona) makes background,
# non-essential calls to the REAL api.anthropic.com (mcp-registry, telemetry,
# session "teleport") using the persona credential. Against the datalab/vLLM
# proxy that key 401s there, and the SDK surfaces the 401 as "not authenticated ·
# run /login", killing an otherwise-working session mid-run. Disable that traffic
# so only inference (→ ANTHROPIC_BASE_URL) ever leaves the container.
c.DockerSpawner.environment["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
c.DockerSpawner.environment["DISABLE_TELEMETRY"] = "1"

# --- Auth: DUMMY, local dev only. Replace with a real authenticator for prod --
c.JupyterHub.authenticator_class = "jupyterhub.auth.DummyAuthenticator"
c.DummyAuthenticator.password = os.environ.get("JUPYTERHUB_DUMMY_PASSWORD", "changeme")

c.JupyterHub.bind_url = "http://:8000"
