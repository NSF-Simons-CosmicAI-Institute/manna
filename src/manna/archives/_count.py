"""CountTarget — how to build a positional COUNT query for one archive table.

The pure, dependency-free half of the counting facade (mirrors `_audit.py`):
each geometry variant renders its own ADQL WHERE predicate, and `CountTarget`
bundles that with the table, the count expression, and the sync/async mode.
`vo_count_observations` / `vo_survey_target` read these; the archives declare
them. No network code lives here, so predicate-building is unit-testable.
"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Q3CRadial:
    """Indexed cone for q3c-clustered tables (NOIRLab Data Lab).

    ADQL CONTAINS/POINT are NOT translated there (they reach PostgreSQL and
    error); `q3c_radial_query(...) = 't'` is the working indexed form.
    """

    ra_col: str
    dec_col: str

    def predicate(self, ra: float, dec: float, radius_deg: float) -> str:
        return f"q3c_radial_query({self.ra_col}, {self.dec_col}, {ra}, {dec}, {radius_deg}) = 't'"


@dataclass(frozen=True)
class ContainsPoint:
    """Standard ADQL point-in-circle (Gaia, ESO, NRAO obscore)."""

    ra_col: str
    dec_col: str

    def predicate(self, ra: float, dec: float, radius_deg: float) -> str:
        return (
            f"CONTAINS(POINT('ICRS', {self.ra_col}, {self.dec_col}), "
            f"CIRCLE('ICRS', {ra}, {dec}, {radius_deg})) = 1"
        )


@dataclass(frozen=True)
class IntersectsRegion:
    """Footprint intersect against a region column (ALMA s_region).

    Matches the observed field (mosaics included), not just the pointing centre.
    """

    region_col: str = "s_region"

    def predicate(self, ra: float, dec: float, radius_deg: float) -> str:
        return f"INTERSECTS(CIRCLE('ICRS', {ra}, {dec}, {radius_deg}), {self.region_col}) = 1"


Geometry = Q3CRadial | ContainsPoint | IntersectsRegion


@dataclass(frozen=True)
class CountTarget:
    """How to count observations/sources near a position at one archive.

    `table` — the countable table. `geometry` — the spatial predicate builder.
    `count_expr` — usually COUNT(*); ALMA overrides to COUNT(DISTINCT
    member_ous_uid) because rows are per spectral-window. `mode` — 'sync',
    'auto' (sync then promote on timeout), or 'async' (submit + bounded poll).
    """

    table: str
    geometry: Geometry
    count_expr: str = "COUNT(*)"
    mode: Literal["sync", "auto", "async"] = "sync"


def build_count_adql(target: CountTarget, ra: float, dec: float, radius_deg: float) -> str:
    """`SELECT <count_expr> AS n FROM <table> WHERE <predicate>` — the `AS n`
    alias gives the integer a stable column name to read back."""
    pred = target.geometry.predicate(ra, dec, radius_deg)
    return f"SELECT {target.count_expr} AS n FROM {target.table} WHERE {pred}"
