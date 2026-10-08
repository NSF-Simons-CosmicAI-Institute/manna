# MANNA

<!-- mcp-name: io.github.NSF-Simons-CosmicAI-Institute/manna -->
[![PyPI](https://img.shields.io/pypi/v/manna-mcp)](https://pypi.org/project/manna-mcp/)
[![Documentation](https://readthedocs.org/projects/manna/badge/?version=latest)](https://manna.readthedocs.io/en/latest/)
[![CI](https://github.com/NSF-Simons-CosmicAI-Institute/manna/actions/workflows/ci.yml/badge.svg)](https://github.com/NSF-Simons-CosmicAI-Institute/manna/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/NSF-Simons-CosmicAI-Institute/manna/blob/main/LICENSE)

**MANNA** (*MCP Architecture for NOIRLab, NRAO, and additional Archives*) is an
[MCP](https://modelcontextprotocol.io) server that gives LLM clients such as
Claude Code, Claude Desktop, and Jupyter AI access to astronomical archives
through the standard IVOA interfaces: TAP/ADQL, SIA image search, cone search,
the IVOA registry, and Sesame name resolution. It includes curated notes for
NOIRLab Astro Data Lab, ALMA, CADC, ESO, Gaia, and SDSS, and can reach any
archive listed in the IVOA registry.

Its tools fall into four groups:

- **Connections** call the IVOA interfaces directly: resolve a target name,
  run an ADQL query, search for images or catalog sources by position, search
  the registry.
- **Workflow tools** do a multi-step task in one call: resolve a target, pick
  an archive, run the search or count.
- **Result handling** returns small results inline. A large TAP result becomes
  an async job, and the client receives a result URL and a pyvo snippet to
  fetch it. The server keeps nothing between requests.
- **Archive notes** record each archive's quirks (missing columns, enum values,
  spatial-index hints) so the model sees them before writing ADQL. Every note
  has a check that re-verifies it.

Full documentation, including the reference for every tool, is at
**<https://manna.readthedocs.io>**.

## Installation

Python 3.12 or later. The PyPI distribution is `manna-mcp`; the import package
and the command are both `manna`.

```bash
uvx manna-mcp --stdio        # run without installing: MCP over stdio
pip install manna-mcp        # or install it; `manna` then serves HTTP on :8000
```

The first launch downloads astropy and pyvo, which takes a while. Run
`uvx manna-mcp --stdio` once in a terminal before adding it to a client with a
short startup timeout.

The Docker image and the MCP Registry entry are described under
[Installation](https://manna.readthedocs.io/en/latest/getting-started/installation.html).

## Connect a client

Claude Code:

```bash
claude mcp add manna -- uvx manna-mcp --stdio
```

Claude Desktop, or any client with a JSON config:

```json
{"mcpServers": {"manna": {"command": "uvx", "args": ["manna-mcp", "--stdio"]}}}
```

For a shared HTTP server or Jupyter AI, run `manna` and point the client at
`http://localhost:8000/mcp/`.

Guides:
[Claude Code](https://manna.readthedocs.io/en/latest/getting-started/claude-code.html),
[Claude Desktop](https://manna.readthedocs.io/en/latest/getting-started/claude-desktop.html),
[Jupyter AI](https://manna.readthedocs.io/en/latest/getting-started/jupyter-ai.html),
[a first query](https://manna.readthedocs.io/en/latest/getting-started/first-query.html).

## Configuration

All settings are optional and are read from `MANNA_*` environment variables or
a `.env` file. The two most often changed:

- `MANNA_ARCHIVES=datalab,alma` limits which archives have curated notes.
  Unset means every archive except `nrao`, which is inactive until named here.
- `MANNA_INLINE_ROW_LIMIT=2000` and `MANNA_INLINE_BYTE_LIMIT=262144` raise the
  inline result caps from their small-model defaults to suit a large context
  window such as Claude's.

Every setting is listed in the
[configuration guide](https://manna.readthedocs.io/en/latest/guide/configuration.html).
Adding or removing an archive is covered in the
[archives guide](https://manna.readthedocs.io/en/latest/guide/archives.html).

## Development

```bash
git clone https://github.com/NSF-Simons-CosmicAI-Institute/manna
cd manna
uv sync
uv run pytest --record-mode=none   # offline replay of recorded archive traffic
uv run python -m manna             # server on http://localhost:8000
```

Feature branches are cut from `dev` and merged back by pull request. Tests,
linting, recorded cassettes, the docs build, and releases are described under
[Contributing](https://manna.readthedocs.io/en/latest/contributing/development.html).

## License

MIT. Developed by the
[NSF-Simons CosmicAI Institute](https://github.com/NSF-Simons-CosmicAI-Institute).
