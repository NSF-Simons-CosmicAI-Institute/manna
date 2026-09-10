"""Contract: the MCP Registry listing stays consistent with what we ship.

Publishing to the registry couples four files that are otherwise easy to drift
apart, and every failure mode here is only discovered *after* an immutable PyPI
release:

- The registry proves package ownership by fetching manna-mcp's description
  from PyPI and grepping it for `mcp-name: <server name>`. The description is
  README.md, and PyPI release metadata cannot be edited — a mismatched or
  missing marker means cutting another version.
- Clients build the launch command as `uvx <identifier> <packageArguments>`,
  and uvx resolves an executable named after the package. Without the
  `manna-mcp` console script alias, `uvx manna-mcp` fails with "An executable
  named `manna-mcp` is not provided by package `manna-mcp`".
- `mcp-publisher publish` rejects a server.json whose package version has no
  matching release on PyPI.
"""

import json
import re
import tomllib
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def server_json() -> dict:
    return json.loads((_ROOT / "server.json").read_text())


@pytest.fixture(scope="module")
def pyproject() -> dict:
    return tomllib.loads((_ROOT / "pyproject.toml").read_text())


@pytest.fixture(scope="module")
def readme() -> str:
    return (_ROOT / "README.md").read_text()


def test_readme_carries_the_ownership_marker(server_json, readme):
    """The marker PyPI serves must name exactly the server we publish."""
    found = re.findall(r"mcp-name:\s*(\S+)", readme)
    assert found, (
        "README.md has no `mcp-name:` marker — the registry cannot verify "
        "ownership of the PyPI package without it"
    )
    assert found == [server_json["name"]], (
        f"README marker {found} != server.json name {server_json['name']!r}"
    )


def test_marker_is_followed_by_a_boundary(readme):
    """The validator matches `mcp-name: <name>` up to a boundary.

    Trailing punctuation glued to the name (a sentence-ending period, say)
    silently prevents the match, so keep the marker on its own line or inside
    an HTML comment.
    """
    line = next(line for line in readme.splitlines() if "mcp-name:" in line)
    assert re.fullmatch(r"<!--\s*mcp-name:\s*\S+\s*-->", line.strip()), (
        f"marker line must be a bare HTML comment, got: {line!r}"
    )


def test_namespace_matches_the_github_owner_exactly(server_json):
    """`io.github.<owner>/` must carry the owner's real casing.

    Namespace authorization is case-sensitive: GitHub OIDC grants
    `io.github.NSF-Simons-CosmicAI-Institute/*`, and publishing a lowercased
    name is refused with a 403 that reads, confusingly, as the same string
    twice. v0.7.1 shipped lowercase and had to be replaced — the marker match
    is byte-exact and PyPI descriptions are immutable, so the mistake could not
    be corrected without cutting another version.
    """
    owner = server_json["repository"]["url"].rstrip("/").split("/")[-2]
    assert server_json["name"].startswith(f"io.github.{owner}/"), (
        f"server name {server_json['name']!r} does not match the GitHub owner "
        f"{owner!r} exactly (case included) — publishing will 403"
    )


def test_server_version_matches_the_package_version(server_json, pyproject):
    expected = pyproject["project"]["version"]
    assert server_json["version"] == expected
    assert server_json["packages"][0]["version"] == expected


def test_package_identifier_is_the_distribution_name(server_json, pyproject):
    assert server_json["packages"][0]["identifier"] == pyproject["project"]["name"]


def test_uvx_can_resolve_the_generated_command(server_json, pyproject):
    """`uvx <identifier>` needs a console script named for the distribution."""
    identifier = server_json["packages"][0]["identifier"]
    assert identifier in pyproject["project"]["scripts"], (
        f"no console script named {identifier!r}; `uvx {identifier}` would fail"
    )


def test_stdio_flag_is_passed_to_the_package(server_json):
    """Without --stdio the client would get an HTTP server on a pipe."""
    package = server_json["packages"][0]
    assert package["transport"]["type"] == "stdio"
    values = [arg.get("value") for arg in package.get("packageArguments", [])]
    assert "--stdio" in values


def test_description_fits_the_registry_limit(server_json):
    assert 0 < len(server_json["description"]) <= 100
