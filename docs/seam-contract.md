# Seam contract — what MCP clients may rely on

This document freezes the interface between `astro-archives-mcp` and any MCP
client (CosmicCoder or otherwise). The server is agent-agnostic: it never
assumes a specific agent, model, or client framework (enforced by
`tests/contracts/test_agent_agnostic.py`). Everything a client may depend on
is listed here; anything not listed here is an implementation detail and may
change without notice.

## 1. Transport and URL

- MCP **Streamable HTTP** at **`/mcp/`** — trailing slash required. `POST /mcp`
  307-redirects (Starlette `Mount`); clients that don't follow redirects must
  use `/mcp/` directly.
- `GET /health` is a liveness endpoint (200 when up).
- Off-loopback deployments front the server with auth (bearer/basic at the
  proxy); the server itself is auth-agnostic.

## 2. Large results: the `fetch_recipe` contract

The server **never persists result bytes** (multi-tenant invariant). For an
oversize TAP result, `vo_tap_results` returns:

- `job_url` — the upstream async job,
- `result_url` — the upstream result location,
- `fetch_recipe` — runnable pyvo code the **client executes itself** (anonymous
  access) to load the data.

Behavioral consequence for clients: an agent consuming this server must keep a
code-execution surface (e.g. a notebook kernel) to run `fetch_recipe`. Small
results come back inline; truncation is always signalled by a top-level
`truncated: true` boolean, never silently.

## 3. Error taxonomy

Error payloads always carry:

- `error_class` — the discriminator a client branches on,
- `retry_strategy` — how/whether to retry.

There is no `isError` key (intentional; see `tools/tap.py` docstring). Raw
tracebacks and credentials never appear in payloads (`InternalError` redacts).

## 4. Tool schema stability

The `vo_*` tool names, input schemas, and descriptions ARE the API. The
committed snapshot **`contracts/tool-schema.json`** is the consumer-driven
contract:

- The server CI fails on drift (`tests/contracts/test_tool_schema_snapshot.py`);
  deliberate changes regenerate the snapshot in the same PR
  (`uv run python scripts/dump_tool_schema.py`), making breaking changes
  loud and reviewable.
- Clients should pin a server version (GHCR image tag) and test against that
  version's snapshot.

## Versioning and distribution

- Version: `pyproject.toml` (single source), also the GHCR image tag.
- Image: `ghcr.io/<owner>/astro-archives-mcp:<version>` published from `main`;
  `:dev` tracks the `dev` branch. Pin exact versions in production clients.

## Dependency direction

Clients consume this server over HTTP only — the published GHCR image plus the
committed tool-schema snapshot. No client should import this package
(cosmic-coder deliberately does not). Server→client dependencies are forbidden,
permanently: no imports of agent code or model-vendor SDKs
(`tests/contracts/test_agent_agnostic.py`), and the eval dependency group is
never required to run or test the server.
