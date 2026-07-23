# astro-archives-mcp

MCP server exposing IVOA-compliant astronomical archives (NOIRLab Astro Data Lab, NRAO/ALMA, CADC, ESO, Gaia, …) to LLM clients.

## Tools

| Tool | Protocol | Description |
|---|---|---|
| `vo_archive_list` | — | List known archives with endpoint URLs and usage notes |
| `vo_schema_describe` | — | Curated per-table schema facts (missing columns, enum values, spatial index hints) |
| `vo_target_resolve` | Sesame | Resolve an object name (e.g. "M87", "Cygnus A") to RA/Dec coordinates |
| `vo_tap_query` | TAP | Submit sync or async ADQL queries; returns inline or promoted results |
| `vo_tap_status` | TAP | Poll an async job by ID |
| `vo_tap_results` | TAP | Return a completed async job's result URL + pyvo fetch recipe (client fetches the data) |
| `vo_tap_abort` | TAP | Abort a running async job |
| `vo_registry_search` | RegTAP | Search the IVOA registry by keyword or service type |
| `vo_registry_describe` | RegTAP | Describe a specific registry resource (columns, capabilities) |
| `vo_cone_search` | SCS | Simple Cone Search for legacy SCS-only archives |
| `vo_sia_search` | SIA 2.0 | Search for images by position and waveband (returns access URLs to fetch client-side) |

The recommended LLM workflow for a positional query:
1. `vo_target_resolve` — get RA/Dec for a named object
2. `vo_archive_list` — discover the archive and its endpoint
3. `vo_schema_describe` — get table-specific quirks before writing ADQL
4. `vo_registry_describe` — live column introspection
5. `vo_tap_query` (mode=`async` for data reads) — run the query

## Quickstart

```bash
uv sync
uv run pytest --record-mode=none        # 285 tests, offline replay
uv run python -m astro_archives_mcp     # server on http://localhost:8000
```

Smoke test with MCP Inspector:
```bash
npx -y @modelcontextprotocol/inspector --cli http://localhost:8000/mcp --method tools/list
```

## Development

```bash
uv sync                        # install runtime + dev deps
uv run pre-commit install      # enable git pre-commit hooks (once per clone)

uv run ruff check .            # lint
uv run ruff format .           # format
uv run pyright                 # type check (src/, basic mode)
uv run pre-commit run --all-files   # run every hook over the whole tree
```

Pre-commit runs ruff (lint + format), file-hygiene checks, and pyright on each
commit; the full test suite runs in CI, not at commit time.

Branch flow (see `CLAUDE.md` for detail): feature branches `<initials>/<name>`
branch off `dev` and PR into `dev`; `dev` is promoted to `main` via PR. `main`
is protected — it only advances through PRs with passing CI.

## Configuration

All settings are optional — defaults work for local dev. Set via environment variables prefixed `STABLE_` or in a `.env` file:

| Variable | Default | Description |
|---|---|---|
| `STABLE_PORT` | `8000` | HTTP listen port |
| `STABLE_HOST` | `0.0.0.0` | Bind address |
| `STABLE_DEPLOYMENT` | `local` | `local` / `adl` / `tacc` |
| `STABLE_LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `STABLE_TAP_SYNC_TIMEOUT_SECONDS` | `20.0` | Timeout for sync TAP queries |
| `STABLE_JOB_TTL_SECONDS` | `3600` | Async job result retention |

See `.env.example` for a template.

## Docker

```bash
docker build -t astro-archives-mcp:dev .
docker run -p 8000:8000 astro-archives-mcp:dev
```

### Container image

Published to GHCR on every `main` promotion (versioned) and `dev` merge (`:dev`):

    docker pull ghcr.io/dangause/astro-archives-mcp:0.5.0

Pin exact versions in production clients. See `docs/seam-contract.md` for what clients may rely on.

## Forking for a specific deployment

This repo is the multi-archive base. Each archive is one self-contained file — its endpoints, usage notes, and per-table schemas all live in `src/astro_archives_mcp/archives/<short_name>.py`. Shape which archives make curated claims two ways:

- **Physical** — delete the unwanted `src/astro_archives_mcp/archives/<short_name>.py` files. Discovery picks up whatever remains; no other file needs touching.
- **Runtime** — set `STABLE_ARCHIVES=datalab,alma` (comma-separated short_names) to narrow a shared image without deleting files. Unset/empty ⇒ every archive active.

A dropped or deselected archive loses only the server's *curated claims* about it — never its reachability. It's still reachable via `vo_registry_search`.

## Refreshing recorded cassettes

Tests replay archive HTTP traffic from YAML cassettes in `tests/<area>/cassettes/`. To refresh a stale cassette:

```bash
# requires network access to the archive endpoint
rm tests/<area>/cassettes/<test_module>/<test_name>.yaml
uv run pytest tests/<area>/<test_module>.py::<test_name> --record-mode=once
```

Inspect the cassette diff before committing — large changes in the VOTable namespace URI or response headers may indicate an upstream breaking change.
