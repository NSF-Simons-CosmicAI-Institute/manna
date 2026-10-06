# MANNA

<!-- mcp-name: io.github.NSF-Simons-CosmicAI-Institute/manna -->
[![PyPI](https://img.shields.io/pypi/v/manna-mcp)](https://pypi.org/project/manna-mcp/)
[![Documentation](https://readthedocs.org/projects/manna/badge/?version=latest)](https://manna.readthedocs.io/en/latest/)
[![CI](https://github.com/NSF-Simons-CosmicAI-Institute/manna/actions/workflows/ci.yml/badge.svg)](https://github.com/NSF-Simons-CosmicAI-Institute/manna/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/NSF-Simons-CosmicAI-Institute/manna/blob/main/LICENSE)

**MANNA** (*MCP Architecture for NOIRLab, NRAO, and Additional Archives*) is an
[MCP](https://modelcontextprotocol.io) server that lets LLM clients such as
Claude Code, Claude Desktop, and Jupyter AI query astronomical archives through
the standard IVOA interfaces: TAP/ADQL, SIA image search, cone search, the IVOA
registry, and Sesame name resolution. It ships curated notes for NOIRLab Astro
Data Lab, ALMA, CADC, ESO, Gaia, and SDSS, and can reach any other archive
listed in the IVOA registry.

- **Fifteen tools**, from `resolve_target_name` to `run_adql_query`, plus
  workflow tools that do a whole task (resolve the target, pick an archive,
  run the search) in one call.
- **Large results never flood the context.** Small results come back inline. A
  large TAP result becomes an async job, and the client receives a result URL
  plus a pyvo snippet to fetch it. The server stores nothing between requests.
- **Archive notes** tell the model about each archive's quirks (missing
  columns, enum values, spatial-index hints) before it writes ADQL. Every note
  carries a check that re-verifies it.
- Runs over **stdio** (the client launches it) or **Streamable HTTP** (a shared
  server), installed from PyPI, Docker, or the MCP Registry.

## Installation

Python 3.12 or later. The PyPI distribution is `manna-mcp`; the import package
and the command are both `manna`.

```bash
uvx manna-mcp --stdio        # run without installing: MCP over stdio
pip install manna-mcp        # or install it; `manna` then serves HTTP on :8000
```

The first launch downloads astropy and pyvo, which is slow. Run
`uvx manna-mcp --stdio` once in a terminal before wiring it into a client with
a short startup timeout.

Installing from GitHub, the Docker image, and the MCP Registry are covered in
[Installation](https://manna.readthedocs.io/en/latest/getting-started/installation.html).

## Connect a client

**Claude Code**

```bash
claude mcp add manna -- uvx manna-mcp --stdio
```

**Claude Desktop**, or any client that reads a JSON config:

```json
{
  "mcpServers": {
    "manna": {
      "command": "uvx",
      "args": ["manna-mcp", "--stdio"],
      "env": {"MANNA_INLINE_ROW_LIMIT": "2000", "MANNA_INLINE_BYTE_LIMIT": "262144"}
    }
  }
}
```

The two `env` values raise the inline result caps from their small-model
defaults to a size that suits Claude's context window.

**HTTP**, for a shared server or Jupyter AI:

```bash
manna                                                        # http://localhost:8000/mcp/
claude mcp add --transport http manna http://localhost:8000/mcp/   # keep the trailing slash
```

Then ask: *"Which archives do you know about, and what are the coordinates of
M87?"* Step-by-step guides:
[Claude Code](https://manna.readthedocs.io/en/latest/getting-started/claude-code.html),
[Claude Desktop](https://manna.readthedocs.io/en/latest/getting-started/claude-desktop.html),
[Jupyter AI](https://manna.readthedocs.io/en/latest/getting-started/jupyter-ai.html),
[your first query](https://manna.readthedocs.io/en/latest/getting-started/first-query.html).

## Tools

| Tool | Protocol | What it does |
|---|---|---|
| `list_archives` | — | List the known archives with their endpoints and usage notes |
| `describe_table` | — | Curated facts about one table: missing columns, enum values, spatial-index hints |
| `preview_table` | TAP | Columns, curated notes, and a sample of rows for one table, in one call |
| `resolve_target_name` | Sesame | Turn an object name ("M87", "Cygnus A") into RA/Dec |
| `run_adql_query` | TAP | Run an ADQL query, sync or async; inline result or an async-job envelope |
| `get_async_job_status` | TAP | Wait for or check an async job by its `job_url` |
| `get_async_job_results` | TAP | Result URL plus a pyvo fetch recipe for a completed job |
| `abort_async_job` | TAP | Abort a running async job |
| `search_ivoa_registry` | RegTAP | Search the IVOA registry by keyword or service type |
| `describe_ivoa_service` | RegTAP | Tables, columns, and capabilities of one registry resource |
| `search_catalog_by_position` | SCS | Simple cone search against a catalog service |
| `search_images_by_position` | SIA 2.0 | Find images by position and waveband; returns access URLs |
| `find_observations_of_target` | SIA 2.0 / SCS | Resolve a target, pick an archive, and run the image or catalog search |
| `count_observations_near_target` | TAP | Resolve a target, pick an archive, and count observations near it |
| `survey_archives_for_target` | TAP | Per-archive observation counts for one target |

Parameters and return payloads for every tool are in the
[tool reference](https://manna.readthedocs.io/en/latest/reference/tools.html).
Tool names changed in 0.9.0 (the `vo_` prefix was dropped); the old-to-new
mapping is in the
[installation page](https://manna.readthedocs.io/en/latest/getting-started/installation.html#tool-names-before-0-9-0).

## Configuration

Every setting is optional. Set them as environment variables prefixed
`MANNA_`, or in a `.env` file. The ones most deployments touch:

| Variable | Default | What it does |
|---|---|---|
| `MANNA_ARCHIVES` | *(unset)* | Comma-separated archive short names to activate (`datalab,alma`). Unset means every non-paused archive; `nrao` ships paused and must be named to enable it |
| `MANNA_INLINE_ROW_LIMIT` | `200` | Rows an inline result may hold before a TAP result goes async or a cone/SIA result is truncated |
| `MANNA_INLINE_BYTE_LIMIT` | `49152` | The same cap in bytes (48 KiB) |
| `MANNA_ALLOWED_HOSTS` | *(unset)* | Hostnames the server may fetch. Unset allows any public host; private and loopback addresses are always refused |
| `MANNA_HOST` / `MANNA_PORT` | `0.0.0.0` / `8000` | HTTP bind address and port |
| `MANNA_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, or `ERROR` |

The full list, including the async-wait and timeout settings, is in the
[configuration guide](https://manna.readthedocs.io/en/latest/guide/configuration.html);
`.env.example` documents every variable.

Each archive is one file under `src/manna/archives/`. To narrow a deployment,
delete the files you don't want or set `MANNA_ARCHIVES`. A deselected archive
loses only its curated notes; it stays reachable through `search_ivoa_registry`.
See the [archives guide](https://manna.readthedocs.io/en/latest/guide/archives.html)
and the [archive spec](https://manna.readthedocs.io/en/latest/contributing/archives-spec.html)
for how to add one.

## Docker

```bash
docker build -t manna:dev .
docker run --rm -p 8000:8000 -e MANNA_ARCHIVES=datalab,alma manna:dev
curl http://localhost:8000/health
```

Releases also publish an image to
`ghcr.io/nsf-simons-cosmicai-institute/manna` (tags `vX.Y.Z` and `latest`);
the package is currently private to the organisation, so building locally is
the route for everyone else.

## Development

```bash
git clone https://github.com/NSF-Simons-CosmicAI-Institute/manna
cd manna
uv sync                            # runtime + dev deps
uv run pre-commit install          # once per clone
uv run pytest --record-mode=none   # offline replay of recorded archive traffic
uv run ruff check . && uv run pyright
uv run python -m manna             # server on http://localhost:8000
```

Feature branches (`<initials>/<name>`) are cut from `dev` and merged back by
pull request; `dev` is promoted to `main` by pull request. The
[development guide](https://manna.readthedocs.io/en/latest/contributing/development.html)
covers the test layout, re-recording cassettes, and the docs build; the
[evals README](https://github.com/NSF-Simons-CosmicAI-Institute/manna/blob/main/evals/README.md)
describes the live-model evaluation harness.

## Documentation

Full documentation: <https://manna.readthedocs.io>

- [Concepts](https://manna.readthedocs.io/en/latest/guide/concepts.html): connections, workflow tools, result handling, archive notes
- [Large results](https://manna.readthedocs.io/en/latest/guide/large-results.html): what happens when a result exceeds the inline caps
- [Security](https://manna.readthedocs.io/en/latest/guide/security.html): the outbound URL guard and what the server never stores
- [Error reference](https://manna.readthedocs.io/en/latest/reference/errors.html): the `error_class` and `retry_strategy` every error payload carries

## License

MIT. Developed by the [NSF-Simons CosmicAI Institute](https://github.com/NSF-Simons-CosmicAI-Institute).
