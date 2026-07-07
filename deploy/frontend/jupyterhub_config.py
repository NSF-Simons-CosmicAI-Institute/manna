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
    )
    if os.environ.get(k)
}

# --- Auth: DUMMY, local dev only. Replace with a real authenticator for prod --
c.JupyterHub.authenticator_class = "jupyterhub.auth.DummyAuthenticator"
c.DummyAuthenticator.password = os.environ.get("JUPYTERHUB_DUMMY_PASSWORD", "changeme")

c.JupyterHub.bind_url = "http://:8000"
