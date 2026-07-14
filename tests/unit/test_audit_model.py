import pytest

from astro_archives_mcp.archives._audit import AUDIT_EXPECTS, Audit, has_cols, has_table


def test_has_table_sql():
    assert has_table("nsc_dr2.object") == (
        "SELECT table_name FROM tap_schema.tables WHERE table_name = 'nsc_dr2.object'"
    )


def test_has_cols_sql_quotes_and_joins():
    sql = has_cols("tap_schema.obscore", ("instrument_name", "facility_name"))
    assert "table_name = 'tap_schema.obscore'" in sql
    assert "column_name IN ('instrument_name', 'facility_name')" in sql


def test_probe_constructor():
    a = Audit.probe(expect="error", adql="SELECT 1")
    assert a.expect == "error" and a.adql == "SELECT 1" and a.reason == ""


def test_count_constructor_builds_adql_and_keeps_columns():
    a = Audit.count(table="tap_schema.obscore", columns=["instrument_name", "facility_name"])
    assert a.expect == "count"
    assert a.columns == ("instrument_name", "facility_name")
    assert "column_name IN ('instrument_name', 'facility_name')" in a.adql


def test_manual_constructor():
    a = Audit.manual("SIA download recipe — verify by hand")
    assert a.expect == "manual" and a.reason and a.adql == ""


@pytest.mark.parametrize("expect", sorted(AUDIT_EXPECTS - {"manual", "count"}))
def test_probe_expect_requires_adql(expect):
    with pytest.raises(ValueError):
        Audit(expect=expect)  # no adql


def test_count_requires_columns_and_adql():
    with pytest.raises(ValueError):
        Audit(expect="count", adql="SELECT 1")  # no columns


def test_manual_rejects_adql_and_requires_reason():
    with pytest.raises(ValueError):
        Audit(expect="manual", reason="x", adql="SELECT 1")
    with pytest.raises(ValueError):
        Audit(expect="manual")  # no reason


def test_unknown_expect_rejected():
    with pytest.raises(ValueError):
        Audit(expect="bogus", adql="SELECT 1")
