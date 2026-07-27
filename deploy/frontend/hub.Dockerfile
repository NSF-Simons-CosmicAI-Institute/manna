# JupyterHub image for `hub` mode. Bundles JupyterHub + configurable-http-proxy
# (from the base) + DockerSpawner. Spawns the frontend image per user.
FROM quay.io/jupyterhub/jupyterhub:latest

RUN pip install --no-cache-dir dockerspawner

COPY jupyterhub_config.py /srv/jupyterhub/jupyterhub_config.py
WORKDIR /srv/jupyterhub
