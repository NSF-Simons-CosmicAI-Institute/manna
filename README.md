# MANNA

**MANNA** — *MCP Architecture for NOIRLab and NRAO Archives.*

An MCP server exposing IVOA-compliant astronomical archives (NOIRLab Astro Data Lab,
NRAO/ALMA, CADC, ESO, Gaia, …) to LLM clients.

> **Naming:** *MANNA* in prose (it's an acronym); lowercase `manna` for every
> identifier — the Python package, `python -m manna`, the `manna:dev` image tag,
> and the MCP client alias (`mcp__manna__*`). The one exception is the PyPI
> distribution, `manna-mcp` (bare `manna` is admin-prohibited on PyPI).

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
| `vo_find_observations` | SIA 2.0 / SCS | One-call facade: resolves a target name or coordinates, auto-selects an archive by service/waveband, then runs the SIA (image) or SCS (catalog) search — chains `vo_target_resolve` + `vo_archive_list` + `vo_sia_search`/`vo_cone_search` so the model doesn't have to |

The recommended LLM workflow for a positional query:
1. `vo_target_resolve` — get RA/Dec for a named object
2. `vo_archive_list` — discover the archive and its endpoint
3. `vo_schema_describe` — get table-specific quirks before writing ADQL
4. `vo_registry_describe` — live column introspection
5. `vo_tap_query` (mode=`async` for data reads) — run the query

## Install

```bash
pip install manna-mcp                # distribution name; the import + CLI are `manna`
manna                                # boots the server on http://localhost:8000
# or run without installing:
uvx --from manna-mcp manna
```

## Quickstart

```bash
uv sync
uv run pytest --record-mode=none        # 657 tests, offline replay
uv run python -m manna                  # server on http://localhost:8000
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

All settings are optional — defaults work for local dev. Set via environment variables prefixed `MANNA_` or in a `.env` file:

| Variable | Default | Description |
|---|---|---|
| `MANNA_PORT` | `8000` | HTTP listen port |
| `MANNA_HOST` | `0.0.0.0` | Bind address |
| `MANNA_LOG_LEVEL` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `MANNA_TAP_SYNC_TIMEOUT_SECONDS` | `20.0` | Timeout for sync TAP queries |
| `MANNA_ALLOWED_HOSTS` | *(unset)* | Comma-separated hostnames the server may fetch (exact or subdomain match). Unset ⇒ any **public** host; private/loopback/link-local targets are refused regardless |
| `MANNA_ARCHIVES` | *(unset)* | Comma-separated archive short_names to activate. Unset/empty ⇒ all archives physically present in `archives/` |
| `MANNA_INLINE_ROW_LIMIT` | `200` | Max rows in an inline result before it's routed to an async job (TAP) or truncated (cone/SIA) |
| `MANNA_INLINE_BYTE_LIMIT` | `49152` | Max bytes in an inline result before the same promotion/truncation applies (48 KiB) |
| `MANNA_REGISTRY_DESCRIBE_BYTE_LIMIT` | `49152` | Above this, `vo_registry_describe` degrades from per-column detail to a table catalog (names + descriptions + column counts) |

See `.env.example` for a template.

## Docker

```bash
docker build -t manna:dev .
docker run -p 8000:8000 manna:dev
```

## Forking for a specific deployment

This repo is the multi-archive base. Each archive is one self-contained file — its endpoints, usage notes, and per-table schemas all live in `src/manna/archives/<short_name>.py`. Shape which archives make curated claims two ways:

- **Physical** — delete the unwanted `src/manna/archives/<short_name>.py` files. Discovery picks up whatever remains; no other file needs touching.
- **Runtime** — set `MANNA_ARCHIVES=datalab,alma` (comma-separated short_names) to narrow a shared image without deleting files. Unset/empty ⇒ every archive active.

A dropped or deselected archive loses only the server's *curated claims* about it — never its reachability. It's still reachable via `vo_registry_search`.

## Refreshing recorded cassettes

Tests replay archive HTTP traffic from YAML cassettes in `tests/<area>/cassettes/`. To refresh a stale cassette:

```bash
# requires network access to the archive endpoint
rm tests/<area>/cassettes/<test_module>/<test_name>.yaml
uv run pytest tests/<area>/<test_module>.py::<test_name> --record-mode=once
```

Inspect the cassette diff before committing — large changes in the VOTable namespace URI or response headers may indicate an upstream breaking change.

## Docs

- [`docs/archives-spec.md`](docs/archives-spec.md) — how per-archive knowledge modules work, and how to author one

Deployment configurations are maintained in a separate repository.
