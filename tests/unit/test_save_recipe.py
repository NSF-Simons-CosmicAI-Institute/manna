"""The save_recipe is executed verbatim in the user's notebook kernel, so
these tests don't just inspect the string — they exec it against a real
DataFrame and read the catalog back, proving the quoting survives ADQL."""

import csv

import pytest

from manna.shaper import attach_cache_fields, build_save_recipe

NASTY_QUERY = "SELECT ra, dec FROM t WHERE name = 'M87, \"the big one\"'\n  AND x > 1"


def _recipe(**overrides):
    kwargs = {
        "fingerprint": "abc123def456",
        "tool": "tap",
        "endpoint": "https://example.org/tap",
        "archive": "alma",
        "query": NASTY_QUERY,
        "truncated": False,
    }
    kwargs.update(overrides)
    return build_save_recipe(**kwargs)


def test_recipe_shape_and_path():
    r = _recipe()
    assert r["path"] == "manna_cache/abc123def456.csv"
    assert "re-run" in r["instructions"] or "re-submit" in r["instructions"]
    assert "QUOTE_ALL" in r["code"]
    assert "manna_cache/catalog.csv" in r["code"]


def test_recipe_code_is_valid_python_despite_nasty_query():
    # Embedded quotes/commas/newlines in the ADQL must not break the snippet.
    compile(_recipe()["code"], "<save_recipe>", "exec")


def test_recipe_executes_and_catalog_roundtrips(tmp_path, monkeypatch):
    pd = pytest.importorskip("pandas")
    monkeypatch.chdir(tmp_path)
    df = pd.DataFrame({"ra": [187.7, 12.3], "dec": [12.39, -4.5]})
    code = _recipe(maxrec=5000)["code"]

    exec(code, {"df": df})  # first save: creates dir, CSV, catalog with header
    exec(code, {"df": df})  # second save: same fingerprint replaces the row

    saved = pd.read_csv(tmp_path / "manna_cache" / "abc123def456.csv")
    assert len(saved) == 2

    with open(tmp_path / "manna_cache" / "catalog.csv", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == [
        "fingerprint",
        "tool",
        "endpoint",
        "archive",
        "query",
        "target",
        "n_rows",
        "truncated",
        "maxrec",
        "csv_path",
        "saved_at",
    ]
    assert len(rows) == 2  # header + one row — rerun replaced, not duplicated
    assert rows[1][4] == NASTY_QUERY  # quoting round-trips the ADQL intact
    assert rows[1][6] == "2"  # n_rows == len(df)
    assert rows[1][7] == "False"  # truncated flag
    assert rows[1][8] == "5000"  # maxrec recorded when provided
    assert rows[1][9] == "manna_cache/abc123def456.csv"


def test_recipe_rerun_replaces_row_across_other_fingerprints(tmp_path, monkeypatch):
    """Saving A, then B (different fingerprint), then A again must leave
    exactly one row per fingerprint — B's row untouched, A's row refreshed
    (not appended a second time) and positioned after B's since it was
    rewritten last."""
    pd = pytest.importorskip("pandas")
    monkeypatch.chdir(tmp_path)
    df = pd.DataFrame({"ra": [187.7], "dec": [12.39]})

    code_a = _recipe(fingerprint="aaa111", query="SELECT a FROM t")["code"]
    code_b = _recipe(fingerprint="bbb222", query="SELECT b FROM t")["code"]

    exec(code_a, {"df": df})
    exec(code_b, {"df": df})
    exec(code_a, {"df": df})  # rerun/refresh of A

    with open(tmp_path / "manna_cache" / "catalog.csv", newline="") as f:
        rows = list(csv.reader(f))

    assert len(rows) == 3  # header + one row per fingerprint
    body = rows[1:]
    fingerprints = [r[0] for r in body]
    assert sorted(fingerprints) == ["aaa111", "bbb222"]
    assert fingerprints.count("aaa111") == 1
    assert fingerprints.count("bbb222") == 1
    # A's surviving row is the one rewritten last (appended after B's kept row).
    assert body[-1][0] == "aaa111"


def test_recipe_catalog_records_empty_maxrec_when_unknown(tmp_path, monkeypatch):
    pd = pytest.importorskip("pandas")
    monkeypatch.chdir(tmp_path)
    df = pd.DataFrame({"ra": [187.7], "dec": [12.39]})
    code = _recipe()["code"]  # no maxrec override -> defaults to None

    exec(code, {"df": df})

    with open(tmp_path / "manna_cache" / "catalog.csv", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[1][8] == ""  # maxrec unknown -> empty string, not "None"


def test_attach_cache_fields_reads_envelope_state():
    envelope = {"archive": "alma", "truncated": True, "rows": []}
    out = attach_cache_fields(
        envelope,
        fingerprint="abc123def456",
        tool="cone",
        endpoint="https://example.org/scs",
        query="ra=1.000000 dec=2.000000 radius=0.100000",
    )
    assert out is envelope  # mutate-and-return
    assert out["query_fingerprint"] == "abc123def456"
    assert "True" in out["save_recipe"]["code"]  # truncated flag propagated
    assert "alma" in out["save_recipe"]["code"]


def test_attach_cache_fields_sets_next_steps_when_none():
    """Inline envelopes start with next_steps=None; attach must create the list
    so weak models (which ignore nested save_recipe.instructions) still see
    an imperative save action at the top level."""
    envelope = {"archive": "alma", "truncated": False, "rows": [], "next_steps": None}
    out = attach_cache_fields(
        envelope,
        fingerprint="abc123def456",
        tool="cone",
        endpoint="https://example.org/scs",
        query="ra=1.000000 dec=2.000000 radius=0.100000",
    )
    assert isinstance(out["next_steps"], list)
    last = out["next_steps"][-1]
    assert "save_recipe.code" in last
    assert "abc123def456" in last


def test_attach_cache_fields_appends_to_existing_next_steps():
    """The async shape_result_url envelope already has a next_steps list —
    attach must append, not clobber, preserving the existing items."""
    existing_step = "Execute fetch_recipe.code with your code-execution tool."
    envelope = {
        "archive": "alma",
        "truncated": False,
        "rows": [],
        "next_steps": [existing_step],
    }
    out = attach_cache_fields(
        envelope,
        fingerprint="abc123def456",
        tool="tap",
        endpoint="https://example.org/tap",
        query="SELECT 1",
    )
    assert out["next_steps"][0] == existing_step  # preserved
    last = out["next_steps"][-1]
    assert "save_recipe.code" in last
    assert "abc123def456" in last
