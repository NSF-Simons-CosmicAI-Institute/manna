# Releasing

A release publishes three things from one Git tag: a container image on
ghcr.io, the `manna-mcp` package on PyPI, and the server record in the MCP
Registry. The order matters.

## 1. Bump versions on `dev`

In one PR to `dev`:

- `pyproject.toml` — `version = "X.Y.Z"`
- `server.json` — both `version` fields
- `README.md` — if the release renames or adds tools, update the tool table

The release workflow refuses a tag that does not match `pyproject.toml`, and
the registry job refuses one that does not match `server.json`.

## 2. Promote `dev` to `main`

Open a PR `dev → main` and merge it once CI is green. The push to `main` runs
the `package` workflow, which builds the image, health-checks it, smoke-tests
it with the MCP Inspector, and pushes `ghcr.io/nsf-simons-cosmicai-institute/manna:<sha7>`.

**Wait for `package` to finish.** The release workflow re-tags that exact
`<sha7>` image; cutting the release early fails with `manifest unknown`.

## 3. Cut the GitHub Release

Create a release with tag `vX.Y.Z` on `main`. The `release` workflow runs
three independent jobs:

| Job | What it does |
|---|---|
| `release-docker` | re-tags `<sha7>` as `vX.Y.Z` and `latest` on ghcr.io |
| `release-pypi` | builds sdist + wheel and publishes to PyPI with Trusted Publishing (OIDC; no stored token; the `pypi` environment) |
| `release-registry` | after PyPI, waits for the release to be served, then publishes `server.json` with `mcp-publisher` using GitHub OIDC |

## 4. Confirm

```bash
curl -s "https://pypi.org/pypi/manna-mcp/X.Y.Z/json" | head -c 200
curl -s "https://registry.modelcontextprotocol.io/v0.1/servers?search=manna"
docker pull ghcr.io/nsf-simons-cosmicai-institute/manna:vX.Y.Z
```

## Things that have bitten us

- **The README must contain the `mcp-name:` marker.** The registry proves
  ownership of a PyPI package by fetching its description (the README) and
  looking for `mcp-name: io.github.NSF-Simons-CosmicAI-Institute/manna`,
  byte-exact, case-sensitive. PyPI descriptions are immutable, so a release
  without the marker can never be listed. Check before tagging.
- **The registry namespace is case-sensitive** and tied to the GitHub
  organisation through OIDC. Moving the repository to another organisation
  means a new server name; records cannot be renamed.
- **`uvx manna-mcp` must work.** Registry-aware clients build the launch
  command from the package identifier, and `uvx` needs a console script named
  after the package. `pyproject.toml` keeps a `manna-mcp` script alias next to
  `manna` for that reason; any rename of the distribution must keep one.
- **Read the Docs** builds `latest` from `main` on every push; no action
  needed, but a release that adds pages should be checked on the site.
