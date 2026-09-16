# Development

```bash
git clone https://github.com/NSF-Simons-CosmicAI-Institute/manna
cd manna
uv sync                          # runtime + dev deps
uv run pre-commit install        # once per clone
uv run pytest --record-mode=none # offline replay of recorded archive traffic
uv run python -m manna           # server on http://localhost:8000
```

## Checks

```bash
uv run ruff check .                  # lint
uv run ruff format .                 # format
uv run pyright                       # type check (src/, basic mode)
uv run pre-commit run --all-files    # every hook
uv run sphinx-build -W --keep-going -b html docs docs/_build/html   # this site
```

Pre-commit runs ruff, file-hygiene checks, and pyright on each commit. The test
suite and the docs build run in CI, not at commit time.

## Tests

Tests mirror the source tree:

| Directory | What it covers |
|---|---|
| `tests/unit/` | pure functions: result shaping, errors, config, the URL guard |
| `tests/archives/` | registry mechanics, plus one `test_<archive>.py` of content assertions per archive |
| `tests/backends/` | the pyvo/httpx wrappers, against recorded cassettes |
| `tests/tools/` | every tool through the in-memory MCP client |
| `tests/contracts/` | invariants every tool must keep: schema conventions, annotations, the error envelope, pitfall delivery |
| `tests/workflows/` | multi-tool chains |
| `tests/app/` | the Starlette app over HTTP |
| `tests/evals/` | offline unit tests for the eval harness |

Archive HTTP traffic is replayed from YAML cassettes (vcrpy). The default is
replay only. To re-record one test (needs network access):

```bash
rm tests/<area>/cassettes/<test_module>/<test_name>.yaml
uv run pytest tests/<area>/<test_module>.py::<test_name> --record-mode=once
```

Read the cassette diff before committing; a changed VOTable namespace or
response header can mean an upstream change worth an archive note.

## Branch flow

- `main` is stable and only advances by merging `dev`.
- `dev` is the integration target; every feature PR lands there.
- Feature branches are `<initials>/<feature-name>`, for example
  `dpg/sphinx-docs`, and are cut from `dev`.

```bash
git checkout dev && git pull origin dev
git checkout -b <initials>/<feature-name>
# implement, test, lint
gh pr create --base dev
```

CI runs ruff, pyright, the test suite on Python 3.12 and 3.13, the docs build,
a container build with a health check, and an MCP Inspector smoke test.

## Docs

The site is MyST markdown under `docs/`, built with Sphinx and published on
Read the Docs. `uv sync --group docs` installs what the build needs. The tool
reference is generated at build time from the running server
(`docs/_ext/manna_tools.py`), so editing a tool's docstring or parameter
description updates the site. Tutorial notebooks under `docs/tutorials/` are
committed with their outputs and are not executed by the build.
