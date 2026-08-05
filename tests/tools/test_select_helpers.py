import manna.tools._select as sel
from manna.archives._model import Archive


def _a(name, *, waveband, tap=None, count=False, priority=100):
    from manna.archives._count import ContainsPoint, CountTarget

    return Archive(
        short_name=name,
        display_name=name.upper(),
        host_substrings=(f"{name}.x",),
        tap_url=tap,
        waveband=waveband,
        priority=priority,
        count_target=CountTarget(table="t", geometry=ContainsPoint("ra", "dec")) if count else None,
    )


def test_coerce_literal_coords_skips_resolver(monkeypatch):
    monkeypatch.setattr(
        sel, "get_resolver", lambda: (_ for _ in ()).throw(AssertionError("resolver called"))
    )
    assert sel.coerce_or_resolve("187.7 12.4") == (187.7, 12.4)


def test_rank_by_attr_filters_and_orders(monkeypatch):
    archives = (
        _a("b", waveband="radio", count=True, priority=2),
        _a("a", waveband="radio", count=True, priority=1),
        _a("o", waveband="optical", count=True, priority=3),
    )
    monkeypatch.setattr(sel, "active_archives", lambda: archives)
    ranked = sel.rank_by_attr(attr="count_target", waveband="radio", override=None)
    assert [x.short_name for x in ranked] == ["a", "b"]


def test_no_candidate_payload_names_capable(monkeypatch):
    archives = (_a("a", waveband="radio", count=True),)
    monkeypatch.setattr(sel, "active_archives", lambda: archives)
    out = sel.no_candidate_payload(
        attr="count_target", service_label="count", waveband="optical", override=None
    )
    assert out["count"] == 0
    assert "a" in out["hint"]


def test_no_candidate_payload_scopes_registry_hint_when_servicetype_given(monkeypatch):
    archives = (_a("a", waveband="radio", count=True),)
    monkeypatch.setattr(sel, "active_archives", lambda: archives)
    out = sel.no_candidate_payload(
        attr="count_target",
        service_label="count",
        waveband="optical",
        override=None,
        servicetype="tap",
    )
    assert "vo_registry_search(servicetype='tap')" in out["hint"]


def test_no_candidate_payload_bare_registry_hint_when_servicetype_omitted(monkeypatch):
    archives = (_a("a", waveband="radio", count=True),)
    monkeypatch.setattr(sel, "active_archives", lambda: archives)
    out = sel.no_candidate_payload(
        attr="count_target", service_label="count", waveband="optical", override=None
    )
    assert "vo_registry_search(servicetype=" not in out["hint"]
    assert "vo_registry_search" in out["hint"]
