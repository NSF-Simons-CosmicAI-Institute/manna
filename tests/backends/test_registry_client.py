import pytest

from manna.backends.registry import RegistryClient
from manna.errors import ValidationError

# Use ESO TAP_obs for describe-by-IVOID and describe-by-URL: ~58 tables,
# cassette stays small. The DataLab TAP has 4027 tables and produced
# 22 MB cassettes, so we switched the describe tests to ESO.
ESO_TAP_OBS_URL = "https://archive.eso.org/tap_obs"
ESO_TAP_OBS_IVOID = "ivo://eso.org/tap_obs"


@pytest.mark.vcr
def test_search_by_keyword_returns_services():
    client = RegistryClient()
    out = client.search(keywords=["smash"], servicetype=None, waveband=None, maxrec=5)
    assert isinstance(out, list)
    assert len(out) >= 1
    assert any("smash" in (s.get("title") or "").lower() for s in out)
    first = out[0]
    for key in (
        "ivoid",
        "title",
        "description",
        "publisher",
        "tap_url",
        "sia_url",
        "scs_url",
        "ssa_url",
        "waveband",
    ):
        assert key in first


@pytest.mark.vcr
def test_describe_by_ivoid_returns_tap_schema():
    client = RegistryClient()
    out = client.describe(ivoid_or_url=ESO_TAP_OBS_IVOID)
    assert out["ivoid"] == ESO_TAP_OBS_IVOID
    assert "tap" in out["capabilities"]
    assert len(out["tables"]) >= 1
    cols = out["tables"][0]["columns"]
    assert len(cols) >= 1
    assert {"name", "type"}.issubset(cols[0].keys())


@pytest.mark.vcr
def test_describe_by_tap_url_returns_tap_schema():
    client = RegistryClient()
    out = client.describe(ivoid_or_url=ESO_TAP_OBS_URL)
    assert "tap" in out["capabilities"]
    assert len(out["tables"]) >= 1


def test_describe_rejects_garbage_input():
    client = RegistryClient()
    with pytest.raises(ValidationError) as exc:
        client.describe(ivoid_or_url="not-an-ivoid-or-url")
    assert "ivo://" in exc.value.message or "URL" in exc.value.message


def test_describe_by_url_falls_back_to_direct_tap_when_not_registered(
    monkeypatch,
):
    """Bug repro: vo_registry_describe used to fail with 'No such service'
    on any TAP URL not registered in RegTAP — even when the service was
    live and queryable. This test pins the fallback path: when registry
    has no match, we introspect the TAP service directly.

    Live case that motivated this: NRAO's first-party TAP at
    `https://data-query.nrao.edu/tap` works, but RegTAP only has the
    ALMA mirror at almascience.nrao.edu listed under the nrao.edu domain.
    """
    from manna.backends import registry as registry_module

    # Make RegTAP claim no services exist for this URL.
    monkeypatch.setattr(
        registry_module.pyvo.registry,
        "search",
        lambda **_kw: iter([]),
    )

    # Mock the direct-TAP introspection so the test stays hermetic.
    class _FakeTable:
        def __init__(self, name):
            self.name = name
            self.description = f"fake table {name}"
            self.columns = []

    class _FakeTAPService:
        def __init__(self, url):
            self.url = url

        @property
        def tables(self):
            return {
                "tap_schema.obscore": _FakeTable("tap_schema.obscore"),
                "tap_schema.tables": _FakeTable("tap_schema.tables"),
            }

    monkeypatch.setattr(
        registry_module.pyvo.dal,
        "TAPService",
        _FakeTAPService,
    )

    client = RegistryClient()
    out = client.describe(ivoid_or_url="https://data-query.nrao.edu/tap")

    assert out["ivoid"] is None  # not in registry
    assert out["title"] is None
    assert "Direct TAP introspection" in out["description"]
    assert "data-query.nrao.edu/tap" in out["description"]
    assert out["capabilities"] == ["tap"]
    assert {t["name"] for t in out["tables"]} == {
        "tap_schema.obscore",
        "tap_schema.tables",
    }


def test_describe_by_url_propagates_direct_introspection_failure(monkeypatch):
    """When the registry has no match AND direct introspection fails
    (bad URL, service down), surface a clear ArchiveError so the LLM
    knows to abandon or retry — not the misleading 'No such service'."""
    from pyvo.dal.exceptions import DALServiceError

    from manna.backends import registry as registry_module
    from manna.errors import ArchiveError

    monkeypatch.setattr(
        registry_module.pyvo.registry,
        "search",
        lambda **_kw: iter([]),
    )

    class _DeadTAPService:
        def __init__(self, url):
            raise DALServiceError("connect: refused")

    monkeypatch.setattr(
        registry_module.pyvo.dal,
        "TAPService",
        _DeadTAPService,
    )

    client = RegistryClient()
    with pytest.raises(ArchiveError) as exc:
        client.describe(ivoid_or_url="https://does-not-exist.example.org/tap")
    assert "Could not introspect TAP service" in exc.value.message
    assert exc.value.retry_strategy == "wait_and_retry"
