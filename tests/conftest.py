"""Shim around vcrpy's response stub.

astropy.io.votable.parse calls ``response.read(amt, decode_content=True)``
on the urllib3 HTTPResponse it receives. vcrpy's ``VCRHTTPResponse.read``
forwards ``decode_content`` straight to the underlying ``BytesIO``, which
rejects unknown kwargs. We strip ``decode_content`` so replay matches the
behaviour of a real urllib3 response (which simply ignores it for already-
decoded content).

Lives at tests/conftest.py (not a subdirectory) so the patch applies to
every test that uses @pytest.mark.vcr — including the in-memory MCP client
tests under tests/tools/, which exercise the same astropy votable code path.
"""

import pytest
from vcr.stubs import VCRHTTPResponse

from manna.app import build_mcp
from manna.tools import schema as _schema_tool


@pytest.fixture
def mcp_server():
    """In-memory FastMCP instance for tests that talk to it via fastmcp.Client."""
    return build_mcp()


@pytest.fixture(autouse=True)
def _offline_column_fetch(monkeypatch):
    """Keep `vo_schema_describe`'s live column fetch off the network by default.

    The tool queries the archive's `tap_schema.columns` to return real column
    names. Most tests care about the curated-KB half and would otherwise make a
    real call to NOIRLab/NRAO just by describing a table — slow, flaky, and
    outside the vcrpy cassette path (these are KB tests, not backend tests).

    Stubbing the fetch to fail exercises the degrade-to-recipe path, which is the
    honest default for an offline run. A test that wants columns opts in by
    patching `_get_tap` itself — the same monkeypatch seam tools/tap.py uses.
    """

    class _OfflineTap:
        def query(self, *, endpoint, adql, maxrec=10_000):
            raise RuntimeError(f"offline test run: refusing live column fetch to {endpoint}")

    monkeypatch.setattr(_schema_tool, "_get_tap", lambda: _OfflineTap())


@pytest.fixture(autouse=True)
def _offline_dns(monkeypatch):
    """Keep the SSRF guard's hostname resolution off the network.

    ``_url_guard.ensure_safe_url`` resolves each hostname to verify it lands in
    public address space. Left alone that would make ~every tool test depend on
    live DNS for almalscience/noirlab/etc. Stubbing the resolver to a public
    address keeps the suite offline while preserving the guard's real logic:
    tests that exercise *blocking* use IP literals (never resolved) or override
    this fixture explicitly.
    """
    monkeypatch.setattr("manna._url_guard._resolve", lambda host: ["93.184.216.34"])


def _read(self, *args, **kwargs):
    kwargs.pop("decode_content", None)
    return self._content.read(*args, **kwargs)


def _read1(self, *args, **kwargs):
    kwargs.pop("decode_content", None)
    return self._content.read1(*args, **kwargs)


if not getattr(VCRHTTPResponse, "_decode_content_patched", False):
    VCRHTTPResponse.read = _read  # type: ignore[assignment]
    VCRHTTPResponse.read1 = _read1  # type: ignore[assignment]
    VCRHTTPResponse._decode_content_patched = True  # type: ignore[attr-defined]
