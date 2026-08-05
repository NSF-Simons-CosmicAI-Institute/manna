import pytest
from astropy.table import Table

import manna.tools.inspect as inspect_mod


class _Tap:
    def __init__(self, *, cols, sample=None, sample_exc=None):
        self._cols = cols
        self._sample = sample
        self._sample_exc = sample_exc

    def query(self, *, endpoint, adql, maxrec=10_000):
        if adql.startswith("SELECT column_name"):
            return self._cols
        if self._sample_exc:
            raise self._sample_exc
        return self._sample


@pytest.fixture
def known_datalab(monkeypatch):
    # by_short_name -> archive with tap_url; lookup_schema -> curated schema dict
    from manna.archives._model import Archive

    arch = Archive(
        short_name="datalab",
        display_name="Data Lab",
        host_substrings=("d.x",),
        tap_url="http://d/tap",
        waveband="optical",
    )
    monkeypatch.setattr(inspect_mod, "by_short_name", lambda n: arch if n == "datalab" else None)
    return arch


def test_inspect_returns_columns_enums_and_sample(known_datalab, monkeypatch):
    cols = Table({"column_name": ["ra", "dec"], "datatype": ["double", "double"]})
    sample = Table({"ra": [187.7], "dec": [12.4]})
    monkeypatch.setattr(inspect_mod, "_get_tap", lambda: _Tap(cols=cols, sample=sample))
    monkeypatch.setattr(
        inspect_mod, "lookup_schema", lambda *, archive, table: None
    )  # no curated notes is fine

    out = inspect_mod.vo_inspect_table(table="nsc_dr2.object", archive="datalab", sample_rows=1)

    assert {"name": "ra", "datatype": "double"} in out["columns"]
    assert out["sample_status"] == "ok"
    assert out["sample_rows"] and out["sample_rows"][0]["ra"] == pytest.approx(187.7)


def test_inspect_sample_rows_are_json_safe(known_datalab, monkeypatch):
    """Real archive rows carry masked (missing), bytes, and non-finite cells;
    the sample must coerce them to JSON-safe scalars or the MCP structured
    output breaks (regression: masked pmra/pmdec on nsc_dr2.object)."""
    import json

    import numpy as np

    cols = Table({"column_name": ["pmra", "flags", "name"], "datatype": ["double", "int", "char"]})
    # A masked cell (missing value), a NaN, and a bytes value — all non-JSON.
    sample = Table(
        {
            "pmra": np.ma.MaskedArray([1.0], mask=[True]),  # masked → null
            "flags": [float("nan")],  # non-finite → null
            "name": [b"NSC J1234"],  # bytes → str
        }
    )
    monkeypatch.setattr(inspect_mod, "_get_tap", lambda: _Tap(cols=cols, sample=sample))
    monkeypatch.setattr(inspect_mod, "lookup_schema", lambda *, archive, table: None)

    out = inspect_mod.vo_inspect_table(table="nsc_dr2.object", archive="datalab", sample_rows=1)

    row = out["sample_rows"][0]
    assert row["pmra"] is None
    assert row["flags"] is None
    assert row["name"] == "NSC J1234"
    json.dumps(out)  # must not raise — the whole payload is JSON-serializable


def test_inspect_sample_soft_fails_on_error(known_datalab, monkeypatch):
    from manna.errors import ArchiveError

    cols = Table({"column_name": ["s_ra"], "datatype": ["double"]})
    monkeypatch.setattr(
        inspect_mod,
        "_get_tap",
        lambda: _Tap(cols=cols, sample_exc=ArchiveError(message="unfiltered read fails")),
    )
    monkeypatch.setattr(inspect_mod, "lookup_schema", lambda *, archive, table: None)

    out = inspect_mod.vo_inspect_table(table="tap_schema.obscore", archive="datalab", sample_rows=5)

    assert out["columns"] == [{"name": "s_ra", "datatype": "double"}]
    assert out["sample_status"] == "error"
    assert out["sample_rows"] == []


def test_inspect_sample_disabled_when_zero(known_datalab, monkeypatch):
    cols = Table({"column_name": ["ra"], "datatype": ["double"]})
    monkeypatch.setattr(inspect_mod, "_get_tap", lambda: _Tap(cols=cols))
    monkeypatch.setattr(inspect_mod, "lookup_schema", lambda *, archive, table: None)
    out = inspect_mod.vo_inspect_table(table="nsc_dr2.object", archive="datalab", sample_rows=0)
    assert out["sample_status"] == "disabled"


def test_inspect_unknown_archive_soft_fails(monkeypatch):
    monkeypatch.setattr(inspect_mod, "by_short_name", lambda n: None)
    monkeypatch.setattr(inspect_mod, "lookup_schema", lambda *, archive, table: None)
    out = inspect_mod.vo_inspect_table(table="foo.bar", archive="nope")
    assert out["known"] is False
    assert "hint" in out


def test_inspect_infers_archive_from_schema_when_archive_omitted(monkeypatch):
    """No `archive` arg: inferred via a matching Schema.table entry."""
    from manna.archives._model import Archive, Schema

    matching = Archive(
        short_name="datalab",
        display_name="Data Lab",
        host_substrings=("d.x",),
        tap_url="http://d/tap",
        schemas=(Schema(archive="datalab", table="nsc_dr2.object"),),
    )
    other = Archive(
        short_name="nrao",
        display_name="NRAO",
        host_substrings=("n.x",),
        tap_url="http://n/tap",
    )
    monkeypatch.setattr(inspect_mod, "active_archives", lambda: (other, matching))
    monkeypatch.setattr(inspect_mod, "lookup_schema", lambda *, archive, table: matching.schemas[0])

    cols = Table({"column_name": ["ra", "dec"], "datatype": ["double", "double"]})
    monkeypatch.setattr(inspect_mod, "_get_tap", lambda: _Tap(cols=cols, sample=Table({})))

    out = inspect_mod.vo_inspect_table(table="nsc_dr2.object", sample_rows=0)

    assert out["archive"] == "datalab"
    assert out["known"] is True
    assert {"name": "ra", "datatype": "double"} in out["columns"]


def test_inspect_infers_archive_from_notable_tables_when_archive_omitted(monkeypatch):
    """No `archive` arg: inferred via `notable_tables` (no curated Schema entry)."""
    from manna.archives._model import Archive

    matching = Archive(
        short_name="alma",
        display_name="ALMA",
        host_substrings=("a.x",),
        tap_url="http://a/tap",
        notable_tables=("tap_schema.obscore",),
    )
    monkeypatch.setattr(inspect_mod, "active_archives", lambda: (matching,))
    monkeypatch.setattr(inspect_mod, "lookup_schema", lambda *, archive, table: None)

    cols = Table({"column_name": ["s_ra"], "datatype": ["double"]})
    monkeypatch.setattr(inspect_mod, "_get_tap", lambda: _Tap(cols=cols, sample=Table({})))

    out = inspect_mod.vo_inspect_table(table="tap_schema.obscore", sample_rows=0)

    assert out["archive"] == "alma"
    assert out["known"] is False  # no curated Schema, but archive was still inferred
    assert {"name": "s_ra", "datatype": "double"} in out["columns"]


def test_inspect_no_match_and_no_archive_soft_fails(monkeypatch):
    """No `archive` arg and nothing in curated knowledge references the table."""
    from manna.archives._model import Archive

    unrelated = Archive(
        short_name="datalab",
        display_name="Data Lab",
        host_substrings=("d.x",),
        tap_url="http://d/tap",
    )
    monkeypatch.setattr(inspect_mod, "active_archives", lambda: (unrelated,))
    monkeypatch.setattr(inspect_mod, "lookup_schema", lambda *, archive, table: None)

    out = inspect_mod.vo_inspect_table(table="totally.unknown")

    assert out["known"] is False
    assert out["archive"] is None
    assert "hint" in out
