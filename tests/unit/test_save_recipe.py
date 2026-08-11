"""The save_recipe is executed verbatim in the user's notebook kernel, so
these tests don't just inspect the string — they exec it against a real
DataFrame and read the catalog back, proving the quoting survives ADQL."""

import csv

import pytest

from manna.shaper import attach_cache_fields, build_load_recipe, build_save_recipe

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
    exec(code, {"df": df})  # second save: append-only -> a second row, same fingerprint

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
    assert len(rows) == 3  # header + 2 rows — append-only, header written exactly once
    for row in rows[1:]:
        assert row[0] == "abc123def456"
        assert row[4] == NASTY_QUERY  # quoting round-trips the ADQL intact
        assert row[6] == "2"  # n_rows == len(df)
        assert row[7] == "False"  # truncated flag
        assert row[8] == "5000"  # maxrec recorded when provided
        assert row[9] == "manna_cache/abc123def456.csv"


def test_recipe_append_only_reader_dedupes_by_newest_row_per_fingerprint(tmp_path, monkeypatch):
    """Append-only means rerunning a save cell duplicates its fingerprint's
    row rather than replacing it in place — that's the deliberate trade for
    a snippet short enough to survive being retyped by hand. Saving A, then
    B (different fingerprint), then A again yields 3 rows: two for A, one
    for B. Readers are expected to dedupe client-side by taking the LAST
    row per fingerprint (documented in build_save_recipe's docstring and in
    the deployment persona) — this test demonstrates that reader pattern
    lands on A's newest row and B's only row."""
    pd = pytest.importorskip("pandas")
    monkeypatch.chdir(tmp_path)
    df = pd.DataFrame({"ra": [187.7], "dec": [12.39]})

    code_a = _recipe(fingerprint="aaa111", query="SELECT a FROM t")["code"]
    code_b = _recipe(fingerprint="bbb222", query="SELECT b FROM t")["code"]

    exec(code_a, {"df": df})
    exec(code_b, {"df": df})
    exec(code_a, {"df": df})  # rerun of A: appends a duplicate row, doesn't replace

    with open(tmp_path / "manna_cache" / "catalog.csv", newline="") as f:
        rows = list(csv.reader(f))

    assert len(rows) == 4  # header + 3 rows (A, B, A)
    body = rows[1:]
    fingerprints = [r[0] for r in body]
    assert fingerprints == ["aaa111", "bbb222", "aaa111"]

    # Reader-side dedupe: last row per fingerprint wins.
    deduped: dict[str, list[str]] = {}
    for row in body:
        deduped[row[0]] = row
    assert set(deduped) == {"aaa111", "bbb222"}
    assert deduped["aaa111"] is body[2]  # A's newest (last) row, not its first
    assert deduped["bbb222"] is body[1]


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


NASTY_ADQL = "SELECT ra, dec FROM t WHERE name = 'M87, \"the big one\"'\n  AND x > 1"


def test_build_load_recipe_code_compiles():
    r = build_load_recipe(endpoint="https://example.org/tap", adql=NASTY_ADQL)
    compile(r["code"], "<load_recipe>", "exec")


def test_build_load_recipe_shape_and_content():
    r = build_load_recipe(endpoint="https://example.org/tap", adql=NASTY_ADQL)
    assert r["module"] == "pyvo"
    assert repr("https://example.org/tap") in r["code"]
    assert repr(NASTY_ADQL) in r["code"]
    assert "run_sync" in r["code"]
    assert "to_pandas" in r["code"]


def test_attach_cache_fields_fuses_save_into_load_recipe_code():
    """Live runs showed models running load_recipe + plotting but skipping the
    standalone save cell entirely (~50% observed). Fix: saving is folded into
    load_recipe.code as a side effect of the transport cell the model must
    run anyway, rather than a separate cell it can drop."""
    envelope = {"archive": "alma", "truncated": False, "rows": [], "next_steps": None}
    load_recipe = build_load_recipe(endpoint="https://example.org/tap", adql="SELECT 1")
    original_load_code = load_recipe["code"]
    out = attach_cache_fields(
        envelope,
        fingerprint="abc123def456",
        tool="tap",
        endpoint="https://example.org/tap",
        query="SELECT 1",
        load_recipe=load_recipe,
    )
    # Composition: load lines, then the exact save_recipe code, joined by \n —
    # reused verbatim from save_recipe, not a re-derived duplicate string.
    assert out["load_recipe"]["code"] == original_load_code + "\n" + out["save_recipe"]["code"]
    assert out["load_recipe"]["module"] == load_recipe["module"]
    compile(out["load_recipe"]["code"], "<fused load+save recipe>", "exec")
    assert "run_sync" in out["load_recipe"]["code"]
    assert "to_pandas" in out["load_recipe"]["code"]
    assert "manna_cache/catalog.csv" in out["load_recipe"]["code"]
    assert "csv.QUOTE_ALL" in out["load_recipe"]["code"]

    # The passed-in load_recipe dict itself must be untouched (still just the
    # load lines) — attach must not mutate the caller's dict in place.
    assert load_recipe["code"] == original_load_code

    # save_recipe stays attached standalone too (async / cache-only re-save).
    assert out["save_recipe"]["code"] != out["load_recipe"]["code"]

    last = out["next_steps"][-1]
    assert "load_recipe.code" in last
    assert "ONE notebook cell" in last
    assert "fetch_recipe.code" in last
    assert "save_recipe.code" in last


def test_attach_cache_fields_without_load_recipe_has_no_key_and_old_wording():
    envelope = {"archive": "alma", "truncated": False, "rows": [], "next_steps": None}
    out = attach_cache_fields(
        envelope,
        fingerprint="abc123def456",
        tool="tap",
        endpoint="https://example.org/tap",
        query="SELECT 1",
    )
    assert "load_recipe" not in out
    last = out["next_steps"][-1]
    assert "pandas DataFrame named df" in last
    assert "load_recipe.code" not in last


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
