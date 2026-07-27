"""Tests for vo_find_observations — the purpose-driven orchestration facade.

This tool absorbs the resolve -> select-archive -> search chain into one call.
It is a thin facade over the SAME backends the atomic tools use; the atomic
tools (vo_target_resolve / vo_archive_list / vo_sia_search / vo_cone_search)
stay the precision escape hatch.
"""

import pytest
from astropy.table import Table
from fastmcp import Client

import manna.tools.find_observations as find_mod
from manna.archives._audit import Audit
from manna.archives._model import Archive, Note

# ---------- fakes ----------


def _note(text: str) -> Note:
    return Note(id="n", text=text, audit=Audit.manual(reason="test fixture note"))


class _FakeResolver:
    """Records the name it was asked to resolve; returns a fixed hit/miss."""

    def __init__(self, result):
        self._result = result
        self.calls: list[str] = []

    def resolve(self, name: str):
        self.calls.append(name)
        return self._result


class _FakeSearch:
    """Fake SIA/cone backend: records kwargs, returns a small astropy Table."""

    def __init__(self, table=None):
        self._table = (
            table
            if table is not None
            else Table({"access_url": ["http://img/1.fits"], "s_ra": [187.7], "s_dec": [12.4]})
        )
        self.calls: list[dict] = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return self._table


def _archive(short_name, *, waveband, sia_url=None, scs_url=None, priority=100, notes=()):
    return Archive(
        short_name=short_name,
        display_name=short_name.upper(),
        host_substrings=(f"{short_name}.example",),
        sia_url=sia_url,
        scs_url=scs_url,
        waveband=waveband,
        priority=priority,
        usage_notes=tuple(_note(n) for n in notes),
    )


@pytest.fixture
def two_radio_and_optical(monkeypatch):
    """A registry-ordered fleet: a high-priority radio SIA archive, a lower
    radio one, and an optical-only-catalog archive."""
    archives = (
        _archive(
            "radio_a",
            waveband="radio",
            sia_url="http://radio-a/sia",
            priority=1,
            notes=("radio_a: async only for obscore",),
        ),
        _archive("radio_b", waveband="radio", sia_url="http://radio-b/sia", priority=2),
        _archive("opt", waveband="optical", scs_url="http://opt/scs", priority=3),
    )
    monkeypatch.setattr(find_mod, "active_archives", lambda: archives)
    return archives


# ---------- coordinate coercion ----------


def test_explicit_coords_skip_the_resolver(two_radio_and_optical, monkeypatch):
    resolver = _FakeResolver(result=None)  # would fail if called
    sia = _FakeSearch()
    monkeypatch.setattr(find_mod, "_get_resolver", lambda: resolver)
    monkeypatch.setattr(find_mod, "_get_sia", lambda: sia)

    out = find_mod.vo_find_observations(target="187.7 12.4", service="image")

    assert resolver.calls == []  # never resolved a literal coordinate pair
    assert sia.calls[0]["ra"] == pytest.approx(187.7)
    assert sia.calls[0]["dec"] == pytest.approx(12.4)
    assert out["resolved"] == {"target": "187.7 12.4", "ra": 187.7, "dec": 12.4, "frame": "icrs"}


def test_comma_separated_coords_are_accepted(two_radio_and_optical, monkeypatch):
    monkeypatch.setattr(find_mod, "_get_resolver", lambda: _FakeResolver(result=None))
    sia = _FakeSearch()
    monkeypatch.setattr(find_mod, "_get_sia", lambda: sia)

    find_mod.vo_find_observations(target="187.7, 12.4", service="image")

    assert sia.calls[0]["ra"] == pytest.approx(187.7)
    assert sia.calls[0]["dec"] == pytest.approx(12.4)


def test_name_is_resolved_via_sesame(two_radio_and_optical, monkeypatch):
    resolver = _FakeResolver(result=(187.70593, 12.39112))
    sia = _FakeSearch()
    monkeypatch.setattr(find_mod, "_get_resolver", lambda: resolver)
    monkeypatch.setattr(find_mod, "_get_sia", lambda: sia)

    out = find_mod.vo_find_observations(target="M87", service="image")

    assert resolver.calls == ["M87"]
    assert sia.calls[0]["ra"] == pytest.approx(187.70593)
    assert out["resolved"]["target"] == "M87"


def test_unresolvable_name_soft_fails(two_radio_and_optical, monkeypatch):
    monkeypatch.setattr(find_mod, "_get_resolver", lambda: _FakeResolver(result=None))
    # search backend must never be reached
    monkeypatch.setattr(find_mod, "_get_sia", lambda: _FakeSearch())

    out = find_mod.vo_find_observations(target="XYZZY_NOPE", service="image")

    assert out["resolved"] is False
    assert out["target"] == "XYZZY_NOPE"
    assert "message" in out


def test_empty_target_is_a_validation_error(two_radio_and_optical):
    out = find_mod.vo_find_observations(target="   ", service="image")
    assert out["error_class"] == "validation_error"
    assert out["retry_strategy"] == "fix_and_retry"


# ---------- archive selection ----------


def test_waveband_picks_the_highest_priority_matching_archive(two_radio_and_optical, monkeypatch):
    sia = _FakeSearch()
    monkeypatch.setattr(find_mod, "_get_resolver", lambda: _FakeResolver((1.0, 2.0)))
    monkeypatch.setattr(find_mod, "_get_sia", lambda: sia)

    out = find_mod.vo_find_observations(target="Src", service="image", waveband="radio")

    assert out["plan"]["chosen_archive"] == "radio_a"  # priority 1 beats radio_b
    assert sia.calls[0]["endpoint"] == "http://radio-a/sia"
    assert out["plan"]["alternatives"] == ["radio_b"]


def test_archive_override_wins_over_waveband(two_radio_and_optical, monkeypatch):
    sia = _FakeSearch()
    monkeypatch.setattr(find_mod, "_get_resolver", lambda: _FakeResolver((1.0, 2.0)))
    monkeypatch.setattr(find_mod, "_get_sia", lambda: sia)

    out = find_mod.vo_find_observations(target="Src", service="image", archive="radio_b")

    assert out["plan"]["chosen_archive"] == "radio_b"
    assert sia.calls[0]["endpoint"] == "http://radio-b/sia"


def test_catalog_service_uses_the_cone_backend_and_scs_url(two_radio_and_optical, monkeypatch):
    cone = _FakeSearch(table=Table({"ra": [1.0], "dec": [2.0]}))
    monkeypatch.setattr(find_mod, "_get_resolver", lambda: _FakeResolver((1.0, 2.0)))
    monkeypatch.setattr(find_mod, "_get_cone", lambda: cone)

    out = find_mod.vo_find_observations(target="Src", service="catalog", waveband="optical")

    assert out["plan"]["chosen_archive"] == "opt"
    assert cone.calls[0]["endpoint"] == "http://opt/scs"
    assert "radius_deg" in cone.calls[0]


def test_no_matching_archive_returns_a_recovery_hint(two_radio_and_optical, monkeypatch):
    monkeypatch.setattr(find_mod, "_get_resolver", lambda: _FakeResolver((1.0, 2.0)))
    # image service + a waveband that only has a catalog archive => no candidate
    out = find_mod.vo_find_observations(target="Src", service="image", waveband="optical")

    assert out["count"] == 0
    assert "hint" in out


# ---------- provenance & shaping ----------


def test_plan_block_surfaces_chosen_archive_usage_notes(two_radio_and_optical, monkeypatch):
    monkeypatch.setattr(find_mod, "_get_resolver", lambda: _FakeResolver((1.0, 2.0)))
    monkeypatch.setattr(find_mod, "_get_sia", lambda: _FakeSearch())

    out = find_mod.vo_find_observations(target="Src", service="image", waveband="radio")

    assert out["plan"]["usage_notes"] == ["radio_a: async only for obscore"]
    assert out["plan"]["service"] == "image"


def test_result_uses_shape_table_envelope(two_radio_and_optical, monkeypatch):
    monkeypatch.setattr(find_mod, "_get_resolver", lambda: _FakeResolver((1.0, 2.0)))
    monkeypatch.setattr(find_mod, "_get_sia", lambda: _FakeSearch())

    out = find_mod.vo_find_observations(target="Src", service="image", waveband="radio")

    # shape_table's contract: typed columns, row arrays, explicit truncated bool
    assert out["truncated"] is False
    assert isinstance(out["columns"], list)
    assert isinstance(out["rows"], list)
    assert out["archive"] == "radio_a"


def test_radius_and_maxrec_are_threaded_to_the_backend(two_radio_and_optical, monkeypatch):
    sia = _FakeSearch()
    monkeypatch.setattr(find_mod, "_get_resolver", lambda: _FakeResolver((1.0, 2.0)))
    monkeypatch.setattr(find_mod, "_get_sia", lambda: sia)

    find_mod.vo_find_observations(
        target="Src", service="image", waveband="radio", radius_deg=0.25, maxrec=7
    )

    assert sia.calls[0]["size_deg"] == pytest.approx(0.25)
    assert sia.calls[0]["maxrec"] == 7


# ---------- end-to-end registration ----------


@pytest.mark.asyncio
async def test_tool_is_registered_and_callable(mcp_server, monkeypatch):
    monkeypatch.setattr(find_mod, "_get_resolver", lambda: _FakeResolver((1.0, 2.0)))
    monkeypatch.setattr(find_mod, "_get_sia", lambda: _FakeSearch())
    monkeypatch.setattr(
        find_mod,
        "active_archives",
        lambda: (_archive("radio_a", waveband="radio", sia_url="http://radio-a/sia", priority=1),),
    )
    async with Client(mcp_server) as client:
        result = await client.call_tool(
            "vo_find_observations",
            {"target": "M87", "service": "image", "waveband": "radio"},
        )
    payload = result.structured_content
    assert payload["plan"]["chosen_archive"] == "radio_a"
    assert payload["truncated"] is False
