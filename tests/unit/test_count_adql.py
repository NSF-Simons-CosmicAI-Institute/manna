from manna.archives._count import (
    ContainsPoint,
    CountTarget,
    IntersectsRegion,
    Q3CRadial,
    build_count_adql,
)


def test_q3c_predicate():
    p = Q3CRadial("ra", "dec").predicate(187.7, 12.4, 0.1)
    assert p == "q3c_radial_query(ra, dec, 187.7, 12.4, 0.1) = 't'"


def test_contains_point_predicate():
    p = ContainsPoint("s_ra", "s_dec").predicate(200.0, 20.0, 0.1)
    assert p == ("CONTAINS(POINT('ICRS', s_ra, s_dec), CIRCLE('ICRS', 200.0, 20.0, 0.1)) = 1")


def test_intersects_region_predicate():
    p = IntersectsRegion().predicate(83.8, -5.4, 0.05)
    assert p == "INTERSECTS(CIRCLE('ICRS', 83.8, -5.4, 0.05), s_region) = 1"


def test_build_count_adql_default_expr():
    t = CountTarget(table="nsc_dr2.object", geometry=Q3CRadial("ra", "dec"))
    adql = build_count_adql(t, 187.7, 12.4, 0.1)
    assert adql == (
        "SELECT COUNT(*) AS n FROM nsc_dr2.object "
        "WHERE q3c_radial_query(ra, dec, 187.7, 12.4, 0.1) = 't'"
    )


def test_build_count_adql_distinct_expr():
    t = CountTarget(
        table="ivoa.obscore",
        geometry=IntersectsRegion(),
        count_expr="COUNT(DISTINCT member_ous_uid)",
    )
    adql = build_count_adql(t, 11.9, -25.3, 0.1)
    assert adql.startswith("SELECT COUNT(DISTINCT member_ous_uid) AS n FROM ivoa.obscore WHERE ")
    assert "INTERSECTS(CIRCLE('ICRS', 11.9, -25.3, 0.1), s_region) = 1" in adql


def test_count_target_defaults():
    t = CountTarget(table="t", geometry=Q3CRadial("ra", "dec"))
    assert t.count_expr == "COUNT(*)"
    assert t.mode == "sync"
