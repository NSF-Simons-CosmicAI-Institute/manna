# Configuration

Every setting is optional; the defaults work for local development. Settings
are read from environment variables prefixed `MANNA_`, or from a `.env` file
in the working directory. Unknown `MANNA_*` variables are ignored. The source
of truth is `src/manna/config.py`.

| Variable | Default | What it does |
|---|---|---|
| `MANNA_HOST` | `0.0.0.0` | HTTP bind address (HTTP mode only) |
| `MANNA_PORT` | `8000` | HTTP listen port (HTTP mode only) |
| `MANNA_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, or `ERROR`; logs are JSON lines on stderr |
| `MANNA_ARCHIVES` | *(unset)* | Comma-separated archive short names to activate; unset means every non-paused archive ({doc}`archives`) |
| `MANNA_ALLOWED_HOSTS` | *(unset)* | Comma-separated hostnames the server may fetch (exact or subdomain match). Unset allows any **public** host; private, loopback, and link-local targets are refused regardless ({doc}`security`) |
| `MANNA_TAP_SYNC_TIMEOUT_SECONDS` | `20.0` | Client timeout for a TAP `/sync` request; in `mode="auto"` a timeout promotes the query to an async job |
| `MANNA_COUNT_ASYNC_BUDGET_SECONDS` | `15.0` | `count_observations_near_target`: how long to poll an async count job before returning a pending envelope with the `job_url` |
| `MANNA_COUNT_ASYNC_POLL_INTERVAL_SECONDS` | `1.0` | Interval between those polls |
| `MANNA_INLINE_ROW_LIMIT` | `200` | Max rows returned inline before a TAP result is promoted to async or a cone/SIA result is truncated |
| `MANNA_INLINE_BYTE_LIMIT` | `49152` | Same, in bytes of the serialized envelope (48 KiB) |
| `MANNA_REGISTRY_DESCRIBE_BYTE_LIMIT` | `49152` | Above this, `describe_ivoa_service` degrades from per-column detail to a table catalog (names, descriptions, column counts) |

## Presets by model backend

The inline caps default to sizes that suit a small-context local model,
roughly 64K to 128K tokens. Raise them for a frontier model:

| Backend | `MANNA_INLINE_ROW_LIMIT` | `MANNA_INLINE_BYTE_LIMIT` |
|---|---|---|
| Small local model (e.g. gpt-oss-120b on vLLM) | `200` | `49152` |
| Claude (200K+) | `2000` | `262144` |

## Transport

There is one transport flag, on the command line rather than in the
environment: `manna --stdio` serves MCP over stdio for clients that launch the
server themselves. Without it the server binds `MANNA_HOST:MANNA_PORT` and
serves Streamable HTTP at `/mcp/`, plus `/health` and `/ready`.

## Example `.env`

The repository ships `.env.example` with every variable and a comment. Copy it
to `.env` and edit.
