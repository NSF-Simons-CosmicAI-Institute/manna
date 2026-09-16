# MANNA

<!-- mcp-name: io.github.NSF-Simons-CosmicAI-Institute/manna -->
[![Documentation](https://readthedocs.org/projects/manna/badge/?version=latest)](https://manna.readthedocs.io/en/latest/)

**MANNA** — *MCP Architecture for NOIRLab, NRAO, and Additional Archives.*

An MCP server exposing IVOA-compliant astronomical archives (NOIRLab Astro Data Lab,
NRAO/ALMA, CADC, ESO, Gaia, …) to LLM clients.

> **Naming:** *MANNA* in prose (it's an acronym); lowercase `manna` for every
> identifier — the Python package, `python -m manna`, the `manna:dev` image tag,
> and the MCP client alias (`mcp__manna__*`). The one exception is the PyPI
> distribution, `manna-mcp` (bare `manna` is admin-prohibited on PyPI).

## Tools

MANNA has four layers. **Connections** call the standard IVOA interfaces
(TAP, SIA, SCS, RegTAP, Sesame). **Workflow tools** bundle a multi-step task into
one call. **Result handling** returns small results inline and a link plus a
fetch recipe for large ones. **Archive notes** are one file per archive holding
its addresses and notes about its quirks, each note with a check that
re-verifies it. Every tool below is tagged with the layer it belongs to.

| Tool | Protocol | Layer | Description |
|---|---|---|---|
| `list_archives` | — | Archive notes | List known archives with endpoint URLs and usage notes |
| `describe_table` | — | Archive notes | Curated per-table schema facts (missing columns, enum values, spatial index hints) |
| `resolve_target_name` | Sesame | Connections | Resolve an object name (e.g. "M87", "Cygnus A") to RA/Dec coordinates |
| `run_adql_query` | TAP | Connections · Result handling | Submit sync or async ADQL queries; returns inline or promoted results |
| `get_async_job_status` | TAP | Connections | Poll an async job by ID |
| `get_async_job_results` | TAP | Connections · Result handling | Return a completed async job's result URL + pyvo fetch recipe (client fetches the data) |
| `abort_async_job` | TAP | Connections | Abort a running async job |
| `search_ivoa_registry` | RegTAP | Connections | Search the IVOA registry by keyword or service type |
| `describe_ivoa_service` | RegTAP | Connections · Result handling | Describe a specific registry resource (columns, capabilities) |
| `search_catalog_by_position` | SCS | Connections · Result handling | Simple Cone Search for legacy SCS-only archives |
| `search_images_by_position` | SIA 2.0 | Connections · Result handling | Search for images by position and waveband (returns access URLs to fetch client-side) |
| `find_observations_of_target` | SIA 2.0 / SCS | Workflow tools | One-call workflow tool: resolves a target name or coordinates, auto-selects an archive by service/waveband, then runs the SIA (image) or SCS (catalog) search — chains `resolve_target_name` + `list_archives` + `search_images_by_position`/`search_catalog_by_position` so the model doesn't have to |
| `count_observations_near_target` | TAP | Workflow tools | Count observations/sources near a target in one call (resolve → select archive → `COUNT`) |
| `survey_archives_for_target` | TAP | Workflow tools | Survey which archives hold data for a target, with per-archive counts |
| `preview_table` | TAP | Workflow tools · Archive notes | Columns + curated enums/notes + a sample of rows for one table, in one call |

**Renamed in 0.9.0.** Tool names dropped the `vo_` prefix for verb-first,
descriptive names; clients pinned to the old names must update.

| Before 0.9.0 | Now |
|---|---|
| `vo_archive_list` | `list_archives` |
| `vo_schema_describe` | `describe_table` |
| `vo_inspect_table` | `preview_table` |
| `vo_target_resolve` | `resolve_target_name` |
| `vo_tap_query` | `run_adql_query` |
| `vo_tap_status` | `get_async_job_status` |
| `vo_tap_results` | `get_async_job_results` |
| `vo_tap_abort` | `abort_async_job` |
| `vo_registry_search` | `search_ivoa_registry` |
| `vo_registry_describe` | `describe_ivoa_service` |
| `vo_cone_search` | `search_catalog_by_position` |
| `vo_sia_search` | `search_images_by_position` |
| `vo_find_observations` | `find_observations_of_target` |
| `vo_count_observations` | `count_observations_near_target` |
| `vo_survey_target` | `survey_archives_for_target` |

The recommended LLM workflow for a positional query:
1. `resolve_target_name` — get RA/Dec for a named object
2. `list_archives` — discover the archive and its endpoint
3. `describe_table` — get table-specific quirks before writing ADQL
4. `describe_ivoa_service` — live column introspection
5. `run_adql_query` (mode=`async` for data reads) — run the query

## Install

```bash
pip install manna-mcp                # distribution name; the import + CLI are `manna`
manna                                # boots the server on http://localhost:8000
# or run without installing:
uvx manna-mcp
```

### As an MCP server in a client

MANNA speaks stdio with `--stdio`, and streamable HTTP otherwise. For a stdio
client (Claude Desktop, Claude Code, IDE extensions):

```bash
claude mcp add manna -- uvx manna-mcp --stdio
```

or, editing a client config by hand:

```json
{"mcpServers": {"manna": {"command": "uvx", "args": ["manna-mcp", "--stdio"]}}}
```

The first launch resolves astropy and pyvo, which is a large download; run
`uvx manna-mcp --stdio` once in a terminal before wiring it into a client whose
startup timeout is short.

## Quickstart

```bash
uv sync
uv run pytest --record-mode=none        # 732 tests, offline replay
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
| `MANNA_ARCHIVES` | *(unset)* | Comma-separated archive short_names to activate. Unset/empty ⇒ all archives physically present in `archives/` except paused ones (`nrao` ships paused; name it here to re-enable) |
| `MANNA_INLINE_ROW_LIMIT` | `200` | Max rows in an inline result before it's routed to an async job (TAP) or truncated (cone/SIA) |
| `MANNA_INLINE_BYTE_LIMIT` | `49152` | Max bytes in an inline result before the same promotion/truncation applies (48 KiB) |
| `MANNA_REGISTRY_DESCRIBE_BYTE_LIMIT` | `49152` | Above this, `describe_ivoa_service` degrades from per-column detail to a table catalog (names + descriptions + column counts) |

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
- **Paused** — an archive can set `paused="<reason>"` to ship inactive by default without losing its notes. `nrao` is paused while NRAO rebuilds its TAP service; `MANNA_ARCHIVES=datalab,alma,nrao` re-enables it.

A dropped or deselected archive loses only the server's *curated claims* about it — never its reachability. It's still reachable via `search_ivoa_registry`.

## Refreshing recorded cassettes

Tests replay archive HTTP traffic from YAML cassettes in `tests/<area>/cassettes/`. To refresh a stale cassette:

```bash
# requires network access to the archive endpoint
rm tests/<area>/cassettes/<test_module>/<test_name>.yaml
uv run pytest tests/<area>/<test_module>.py::<test_name> --record-mode=once
```

Inspect the cassette diff before committing — large changes in the VOTable namespace URI or response headers may indicate an upstream breaking change.

## Docs

Full documentation: <https://manna.readthedocs.io> — installation, client
setup (Claude Code, Claude Desktop, Jupyter AI), a guide to how results and
archive notes work, the generated tool reference, and tutorials.

- [`docs/archives-spec.md`](docs/archives-spec.md) — how archive notes (per-archive modules) work, and how to author one

Deployment configurations are maintained in a separate repository.
