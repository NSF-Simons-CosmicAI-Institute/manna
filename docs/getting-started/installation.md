# Installation

MANNA is a Python package. The distribution on PyPI is **`manna-mcp`**; the
import package and the command-line entry point are both **`manna`** (bare
`manna` is reserved on PyPI). Python 3.12 or later is required.

The first launch downloads astropy and pyvo, which is large. Run the server once
in a terminal before wiring it into a client whose startup timeout is short.

## From PyPI

::::{tab-set}

:::{tab-item} uvx (no install)
```bash
uvx manna-mcp --stdio        # MCP over stdio, for Claude Code / Claude Desktop
uvx manna-mcp                # HTTP server on http://localhost:8000
```
:::

:::{tab-item} uv tool
```bash
uv tool install manna-mcp
manna --stdio
```
:::

:::{tab-item} pip
```bash
python -m venv .venv && source .venv/bin/activate
pip install manna-mcp
manna                        # HTTP server on http://localhost:8000
```
:::

::::

`manna-mcp` and `manna` are both installed as commands; they are the same
program. `uvx` needs a command named after the package, which is why the
`manna-mcp` alias exists.

Tool names changed in 0.9.0 (they lost their old two-letter prefix — see the
README's "Renamed in 0.9.0" section). These pages describe 0.9.0 or later;
check what you have with `pip show manna-mcp` or the `/health` endpoint,
which reports the version.

## From GitHub

Install the current `main` branch without cloning:

```bash
pip install "manna-mcp @ git+https://github.com/NSF-Simons-CosmicAI-Institute/manna@main"
# or, without installing:
uvx --from "git+https://github.com/NSF-Simons-CosmicAI-Institute/manna@main" manna --stdio
```

Replace `@main` with a tag (`@v0.9.0`) or a branch (`@dev`) as needed.

To work on the code, clone it and use uv:

```bash
git clone https://github.com/NSF-Simons-CosmicAI-Institute/manna
cd manna
uv sync
uv run python -m manna       # server on http://localhost:8000
```

See {doc}`../contributing/development` for tests, linting, and the branch flow.

## Docker

Every release publishes a container image to the GitHub Container Registry:

| Tag | Meaning |
|---|---|
| `ghcr.io/nsf-simons-cosmicai-institute/manna:vX.Y.Z` | a release |
| `ghcr.io/nsf-simons-cosmicai-institute/manna:latest` | the newest release |
| `ghcr.io/nsf-simons-cosmicai-institute/manna:<sha7>` | a build of one commit on `main` |

```bash
docker run --rm -p 8000:8000 ghcr.io/nsf-simons-cosmicai-institute/manna:latest
curl http://localhost:8000/health
```

The image serves MCP over HTTP at `http://localhost:8000/mcp/` and takes the
same `MANNA_*` environment variables as the CLI ({doc}`../guide/configuration`):

```bash
docker run --rm -p 8000:8000 -e MANNA_ARCHIVES=datalab,alma ghcr.io/nsf-simons-cosmicai-institute/manna:latest
```

```{note}
The package is currently **private** on ghcr.io; pulling it needs a GitHub
account with read access to the NSF-Simons-CosmicAI-Institute organization
(`docker login ghcr.io`). Until it is made public, build the image locally:

    git clone https://github.com/NSF-Simons-CosmicAI-Institute/manna
    cd manna && docker build -t manna:dev . && docker run --rm -p 8000:8000 manna:dev
```

## From the MCP Registry

MANNA is listed in the [official MCP Registry](https://registry.modelcontextprotocol.io)
as **`io.github.NSF-Simons-CosmicAI-Institute/manna`**. Look it up with:

```bash
curl -s "https://registry.modelcontextprotocol.io/v0.1/servers?search=manna"
```

The record points at the PyPI package and resolves to the launch command
`uvx manna-mcp --stdio`. A registry-aware client can install MANNA from that
record directly; the pages that follow show the same configuration by hand for
{doc}`claude-code`, {doc}`claude-desktop`, and {doc}`jupyter-ai`.

## Verify

```bash
manna &                      # HTTP mode
curl -s http://localhost:8000/health
# {"status":"ok","version":"{{ release }}"}
npx -y @modelcontextprotocol/inspector --cli http://localhost:8000/mcp --method tools/list
```

MyST substitutions don't expand inside fenced code blocks, so the version
above prints literally; check the running server's actual version against
the installed package (`pip show manna-mcp`) if the two ever look out of
step.

The Inspector call lists 15 tools, beginning with `list_archives`. `POST /mcp`
redirects to `/mcp/`; the Inspector follows the redirect, plain `curl` does not,
so use the trailing slash when you call the endpoint yourself.
