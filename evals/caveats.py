"""Archive-caveat regression suite — Pillar 3.

The server's value is its *curated knowledge* of archive quirks (`known_archives.py`
usage_notes, `schema_kb.py` facts). Those claims are about live third-party archives that
drift underneath us: a sync endpoint starts accepting reads, a missing column reappears, an
untranslated geometry function starts working. When that happens the KB silently goes STALE
and the server starts handing agents wrong advice.

This suite is the guard. It aims for **1:1 coverage of every falsifiable quirk** in the KB,
keyed to `(archive, caveat_id)`, so running it singles out *which* caveat went stale:

  * STILL-TRUE   — the archive still behaves as the KB says.
  * STALE        — the archive changed; the KB claim no longer holds → update the KB.
  * UNREACHABLE  — the archive (or the network) is down; can't judge this run.
  * MANUAL       — the quirk isn't checkable by a single ADQL probe (SIA/DataLink download
                   recipes, advisory naming conventions, async-only behaviours that would
                   make the suite slow/flaky). Listed for completeness — verify by hand.

Probeable caveats are **model-free**: a deterministic probe with an expected outcome
(`ok` / `error` / `empty` / `nonempty` / `count`). `count` checks a group of columns from one
KB note and, on drift, names exactly which column disappeared.

Separating STALE from UNREACHABLE: each archive first runs a **control probe** (a query that
must work if the service is up). If the control fails, the whole archive is UNREACHABLE and
its caveats are not judged — so a network blip is never misreported as "the KB went stale".

    uv run python -m evals.caveats                 # check every caveat
    uv run python -m evals.caveats --archive nrao  # just one archive's caveats
    uv run python -m evals.caveats --list          # list caveats, run nothing
    uv run python -m evals.caveats --probeable     # skip MANUAL rows in the report
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from astro_archives_mcp.backends.tap import TapClient
from astro_archives_mcp.errors import DalQueryError
from astro_archives_mcp.known_archives import by_short_name

RESULTS_DIR = Path(__file__).with_name("results")

# A query that must succeed if the service is up — the STALE-vs-UNREACHABLE discriminator.
# NRAO's /sync fails on obscore *reads* but tap_schema metadata works in sync (that asymmetry
# is itself a caveat), so a metadata probe is the right liveness control for every archive.
_CONTROL_ADQL = "SELECT TOP 1 table_name FROM tap_schema.tables"


@dataclass(frozen=True)
class Caveat:
    """One falsifiable claim from the KB, plus the probe that re-checks it live."""

    archive: str  # short_name in KNOWN_ARCHIVES
    caveat_id: str  # stable slug, unique within an archive
    claim: str  # human-readable, quoted/paraphrased from the KB
    expect: str  # ok | error | empty | nonempty | count | manual
    adql: str = ""  # the probe query ("" for manual)
    columns: tuple[str, ...] = field(default_factory=tuple)  # expected set for `count`
    source: str = ""  # where in the KB this quirk lives (for the "update this" pointer)
    control_adql: str = _CONTROL_ADQL


# --------------------------------------------------------------------------- #
# ADQL builders — keep the probes uniform and the intent obvious.
# --------------------------------------------------------------------------- #
def _has_table(table: str) -> str:
    return f"SELECT table_name FROM tap_schema.tables WHERE table_name = '{table}'"


def _has_cols(table: str, columns: tuple[str, ...]) -> str:
    inlist = ", ".join(f"'{c}'" for c in columns)
    return (
        f"SELECT column_name FROM tap_schema.columns "
        f"WHERE table_name = '{table}' AND column_name IN ({inlist})"
    )


def _cols(
    archive: str, table: str, cid: str, claim: str, columns: tuple[str, ...], source: str
) -> Caveat:
    """A `count` caveat: every listed column must still be present in the table."""
    return Caveat(archive, cid, claim, "count", _has_cols(table, columns), tuple(columns), source)


def _manual(archive: str, cid: str, claim: str, source: str) -> Caveat:
    return Caveat(archive, cid, claim, "manual", source=source)


_UN = "src/astro_archives_mcp/known_archives.py"
_KB = "src/astro_archives_mcp/schema_kb.py"


# --------------------------------------------------------------------------- #
# The caveats — 1:1 with the KB. Each maps to a specific usage_note / schema_kb entry.
# --------------------------------------------------------------------------- #
_ALMA = (
    Caveat(
        "alma",
        "sync-spatial-ok",
        "Spatial filters (INTERSECTS on s_region) work directly in /sync — no async needed.",
        "ok",
        "SELECT TOP 1 s_ra, s_dec FROM ivoa.obscore "
        "WHERE INTERSECTS(CIRCLE('ICRS', 201.365, -43.019, 0.05), s_region) = 1",
        source=f"{_UN} alma:sync-spatial",
    ),
    _cols(
        "alma",
        "ivoa.obscore",
        "granularity-key",
        "member_ous_uid is the canonical downloadable-dataset key (rows are finer: spw x execution).",
        ("member_ous_uid",),
        f"{_UN} alma:granularity / {_KB} alma:ivoa.obscore",
    ),
    _cols(
        "alma",
        "ivoa.obscore",
        "qa-flag-columns",
        "science_observation / qa2_passed 'T'/'F' char flags exist.",
        ("science_observation", "qa2_passed"),
        f"{_UN} alma:qa-flags",
    ),
    _cols(
        "alma",
        "ivoa.obscore",
        "literature-columns",
        "Literature/PI-discovery columns exist (pi_name, proposal_authors, first_author, "
        "bib_reference, pub_title, publication_year, …).",
        (
            "obs_creator_name",
            "pi_name",
            "proposal_authors",
            "first_author",
            "authors",
            "pub_title",
            "pub_abstract",
            "publication_year",
            "bib_reference",
            "proposal_abstract",
        ),
        f"{_UN} alma:literature",
    ),
    _cols(
        "alma",
        "ivoa.obscore",
        "data-rights-columns",
        "data_rights (Public/Proprietary) and obs_release_date exist.",
        ("data_rights", "obs_release_date"),
        f"{_UN} alma:data-rights / {_KB} alma:ivoa.obscore",
    ),
    _cols(
        "alma",
        "ivoa.obscore",
        "enum-columns",
        "Controlled-vocabulary columns scientific_category / dataproduct_type exist.",
        ("scientific_category", "dataproduct_type"),
        f"{_KB} alma:ivoa.obscore",
    ),
    _cols(
        "alma",
        "ivoa.obscore",
        "spatial-columns",
        "s_ra/s_dec (pointing centre) and s_region (WKT footprint) exist.",
        ("s_ra", "s_dec", "s_region"),
        f"{_KB} alma:ivoa.obscore",
    ),
    _cols(
        "alma",
        "ivoa.obscore",
        "band-list-column",
        "band_list (space-separated receiver bands) exists.",
        ("band_list",),
        f"{_KB} alma:ivoa.obscore",
    ),
    _cols(
        "alma",
        "ivoa.obscore",
        "calib-level-column",
        "calib_level exists (2 = Member-OUS, 3 = Group-OUS products).",
        ("calib_level",),
        f"{_KB} alma:ivoa.obscore",
    ),
    _cols(
        "alma",
        "ivoa.obscore",
        "frequency-columns",
        "frequency / frequency_support / em_min / em_max exist.",
        ("frequency", "frequency_support", "em_min", "em_max"),
        f"{_KB} alma:ivoa.obscore",
    ),
    Caveat(
        "alma",
        "sourcecatalogue-table",
        "sourcecatalogue.source_cone_search (calibrator/source flux catalogue) exists.",
        "nonempty",
        _has_table("sourcecatalogue.source_cone_search"),
        source=f"{_UN} alma:sourcecatalogue / {_KB} alma:sourcecatalogue.source_cone_search",
    ),
    _cols(
        "alma",
        "sourcecatalogue.source_cone_search",
        "sourcecat-columns",
        "source_cone_search columns m_ra/m_dec/m_frequency/m_flux/band_name/source_names exist.",
        ("m_ra", "m_dec", "m_frequency", "m_flux", "band_name", "source_names", "catalogue_name"),
        f"{_KB} alma:sourcecatalogue.source_cone_search",
    ),
    _manual(
        "alma",
        "unfiltered-scan-timeout",
        "Unfiltered full-table scans / aggregates (DISTINCT, GROUP BY, no WHERE) time out on /sync.",
        f"{_UN} alma:sync-timeout",
    ),
    _manual(
        "alma",
        "target-name-calibrator",
        "target_name often holds a calibrator designation, not a popular source name — match by position.",
        f"{_UN} alma:target-name",
    ),
    _manual(
        "alma",
        "siav2-service",
        "Exposes a SIAv2 service at almascience.nrao.edu/sia2 for positional image discovery.",
        f"{_UN} alma:siav2",
    ),
    _manual(
        "alma",
        "datalink-downloads",
        "Downloads go through DataLink: access_url -> datalink/sync?ID=<member_ous_uid> VOTable.",
        f"{_UN} alma:datalink",
    ),
    _manual(
        "alma",
        "access-format-truncated",
        "access_format is truncated to 9 chars ('applicati') — don't rely on it to detect DataLink.",
        f"{_UN} alma:datalink",
    ),
    _manual(
        "alma",
        "mirrors",
        "Mirrored at nrao.edu (NA), eso.org (EU), nao.ac.jp (EA) — identical data over TAP/SIAv2/DataLink.",
        f"{_UN} alma:mirrors",
    ),
    _manual(
        "alma",
        "sourcecat-null-geometry",
        "source_cone_search s_ra_deg/s_dec_deg can be NULL -> CONTAINS raises ORA-13032; filter on m_ra/m_dec.",
        f"{_KB} alma:sourcecatalogue.source_cone_search",
    ),
    _manual(
        "alma",
        "sourcecat-non-alma-band",
        "source_cone_search band_name includes 'non-ALMA Band' rows (VLBI catalogue entries).",
        f"{_KB} alma:sourcecatalogue.source_cone_search",
    ),
)

# NRAO's /sync 5xxs on obscore *reads*, so column checks use tap_schema metadata (sync-OK).
_NRAO = (
    Caveat(
        "nrao",
        "sync-5xx-on-obscore",
        "The /sync endpoint returns 5xx on reads against tap_schema.obscore (even SELECT TOP 1).",
        "error",
        "SELECT TOP 1 * FROM tap_schema.obscore",
        source=f"{_UN} nrao:sync-async",
    ),
    Caveat(
        "nrao",
        "obscore-ivoa-absent",
        "ObsCore is NOT at the standard ivoa.obscore (that table is absent).",
        "empty",
        _has_table("ivoa.obscore"),
        source=f"{_UN} nrao:obscore-location",
    ),
    Caveat(
        "nrao",
        "obscore-at-tap-schema",
        "ObsCore lives at the non-standard tap_schema.obscore.",
        "nonempty",
        _has_table("tap_schema.obscore"),
        source=f"{_UN} nrao:obscore-location",
    ),
    Caveat(
        "nrao",
        "no-dataproduct-subtype",
        "The standard ObsCore column dataproduct_subtype is ABSENT from tap_schema.obscore.",
        "empty",
        "SELECT column_name FROM tap_schema.columns "
        "WHERE table_name = 'tap_schema.obscore' AND column_name = 'dataproduct_subtype'",
        source=f"{_UN} nrao:missing-subtype / {_KB} nrao:tap_schema.obscore",
    ),
    _cols(
        "nrao",
        "tap_schema.obscore",
        "instrument-facility-columns",
        "instrument_name (EVLA/VLA/VLBA/GBT) and facility_name (NRAO) columns exist.",
        ("instrument_name", "facility_name"),
        f"{_UN} nrao:enums / {_KB} nrao:tap_schema.obscore",
    ),
    _cols(
        "nrao",
        "tap_schema.obscore",
        "obscore-extension-columns",
        "NRAO extension columns exist (project_code, configuration, num_antennas, max_uv_dist, "
        "spw_names, center_frequencies, bandwidths, nums_channels, spectral_resolutions, "
        "aggregate_bandwidth, scan_num, proprietary_status, qa_notes).",
        (
            "project_code",
            "configuration",
            "num_antennas",
            "max_uv_dist",
            "spw_names",
            "center_frequencies",
            "bandwidths",
            "nums_channels",
            "spectral_resolutions",
            "aggregate_bandwidth",
            "scan_num",
            "proprietary_status",
            "qa_notes",
        ),
        f"{_UN} nrao:extensions",
    ),
    _cols(
        "nrao",
        "tap_schema.obscore",
        "freq-extension-columns",
        "freq_min/freq_max extension columns (Hz) exist.",
        ("freq_min", "freq_max"),
        f"{_UN} nrao:freq-columns",
    ),
    _manual(
        "nrao",
        "async-required-all-data",
        "All DATA queries must use mode='async' (sync 5xxs on obscore reads).",
        f"{_UN} nrao:sync-async",
    ),
    _manual(
        "nrao",
        "spatial-predicate-required",
        "Even in async, queries lacking a CIRCLE/CONTAINS spatial predicate tend to error.",
        f"{_UN} nrao:spatial-required",
    ),
    _manual(
        "nrao",
        "lower-upper-fail",
        "ADQL LOWER()/UPPER() FAIL (spec violation) — use exact-case equality or LIKE.",
        f"{_UN} nrao:lower-upper",
    ),
    _manual(
        "nrao",
        "error-summary-empty",
        "On phase=ERROR the UWS error_summary is always empty (no diagnostic).",
        f"{_UN} nrao:error-summary",
    ),
    _manual(
        "nrao",
        "rows-scan-level",
        "Rows are scan-level; for per-observation summaries GROUP BY project_code / obs_publisher_did.",
        f"{_UN} nrao:granularity",
    ),
    _manual(
        "nrao",
        "vlass-target-name-packed",
        "VLASS target_name is a J2000 packed sexagesimal designation, not a source name.",
        f"{_UN} nrao:vlass-target",
    ),
    _manual(
        "nrao",
        "radio-designations",
        "Common sources are under radio designations (M87->3C274, Cygnus A->3C405, …) — match by position.",
        f"{_UN} nrao:radio-names",
    ),
    _manual(
        "nrao",
        "aggregate-partial",
        "ADQL aggregate support is partial — COUNT(DISTINCT ...) with CASE WHEN can fail server-side.",
        f"{_UN} nrao:aggregates",
    ),
    _manual(
        "nrao",
        "freq-em-disagreement",
        "freq_min/freq_max (Hz) disagree with em_min/em_max (m) by ~1% on the same row.",
        f"{_UN} nrao:freq-em",
    ),
    _manual(
        "nrao",
        "vosi-capabilities-404",
        "VOSI partially implemented: /availability and /tables OK, /capabilities is a hard 404.",
        f"{_UN} nrao:vosi",
    ),
)

_GAIA = (
    Caveat(
        "gaia",
        "dr3-default-table",
        "gaiadr3.gaia_source is the default, queryable table (source_id present).",
        "ok",
        "SELECT TOP 1 source_id FROM gaiadr3.gaia_source",
        source=f"{_UN} gaia:releases",
    ),
    Caveat(
        "gaia",
        "dr2-schema-exists",
        "Each release is a separate schema — gaiadr2.gaia_source also exists.",
        "nonempty",
        _has_table("gaiadr2.gaia_source"),
        source=f"{_UN} gaia:releases",
    ),
    _manual(
        "gaia",
        "source-id-join-key",
        "source_id is the canonical join key; astrometry/photometry/RV are split across tables.",
        f"{_UN} gaia:source-id",
    ),
)

_ESO = (
    Caveat(
        "eso",
        "obscore-mixedcase",
        "ESO exposes ObsCore at the mixed-case ivoa.ObsCore table.",
        "ok",
        "SELECT TOP 1 * FROM ivoa.ObsCore",
        source=f"{_UN} eso:notable_tables",
    ),
    _manual(
        "eso",
        "no-usage-notes",
        "ESO has NO curated usage_notes yet (agents flail on its TAP quirks — see issue #41).",
        f"{_UN} eso",
    ),
)

_CADC = (
    Caveat(
        "cadc",
        "tap-reachable",
        "CADC TAP serves the caom2 tables (baseline for the SIA2/DataLink download caveats).",
        "ok",
        "SELECT TOP 1 * FROM caom2.Observation",
        source=f"{_UN} cadc",
    ),
    _cols(
        "cadc",
        "caom2.Observation",
        "obs-collection-column",
        "obs_collection exists (filter by mission: TESS/JWST/CFHT/HST/…).",
        ("obs_collection",),
        f"{_UN} cadc:obs_collection",
    ),
    _manual(
        "cadc",
        "sia2-datalink-indirection",
        "SIA2 access_url points at a DataLink VOTable, not the FITS (check access_format=content=datalink).",
        f"{_UN} cadc:datalink",
    ),
    _manual(
        "cadc",
        "datalink-follow-through",
        "DataLink recipe: GET access_url -> parse VOTable -> row semantics=='#this' -> GET its access_url "
        "for the FITS (see issue #42).",
        f"{_UN} cadc:datalink",
    ),
)

CAVEATS: tuple[Caveat, ...] = _ALMA + _NRAO + _GAIA + _ESO + _CADC

_STATUS = {
    "still_true": "STILL-TRUE ",
    "stale": "  STALE   ",
    "unreachable": "UNREACHABLE",
    "manual": "  MANUAL  ",
}


def _probe(
    client: TapClient, endpoint: str, adql: str, *, retries: int = 1
) -> tuple[str, int, list[str], str]:
    """Run one probe. Returns (outcome, n_rows, first_col_values, detail).

    outcome distinguishes the three cases that must be judged differently:
      * "ok"            — query ran; n_rows / values populated.
      * "query_error"   — the archive *understood* the query and rejected it
                          (DalQueryError). Deterministic → a trustworthy signal
                          that a table/column/geometry changed.
      * "service_error" — a service/network failure (5xx, timeout, unreachable).
                          NOT trustworthy for a success-expecting caveat — could be
                          a transient blip. Retried before giving up.
    """
    last = ""
    for _ in range(retries + 1):
        try:
            table = client.query(endpoint=endpoint, adql=adql, maxrec=200)
        except DalQueryError as exc:
            return "query_error", 0, [], f"{type(exc).__name__}: {exc}"  # semantic, don't retry
        except Exception as exc:  # ArchiveError / timeout / network — retry, then give up
            last = f"{type(exc).__name__}: {exc}"
            continue
        vals = [str(row[0]) for row in table] if table.colnames else []
        return "ok", len(table), vals, ""
    return "service_error", 0, [], last


def _verdict(expect: str, outcome: str, n_rows: int) -> str:
    # A service/network error means we can't judge a success-expecting caveat — but for an
    # error-expecting caveat (e.g. NRAO's sync 5xx, which IS a service error) it's confirmation.
    if outcome == "service_error":
        return "still_true" if expect == "error" else "unreachable"
    if expect == "ok":
        return "still_true" if outcome == "ok" else "stale"
    if expect == "error":
        return "still_true" if outcome != "ok" else "stale"  # query_error still confirms failure
    if expect == "empty":
        if outcome != "ok":
            return "stale"  # a metadata probe that semantically errors → schema changed
        return "still_true" if n_rows == 0 else "stale"
    if expect == "nonempty":
        if outcome != "ok":
            return "stale"
        return "still_true" if n_rows > 0 else "stale"
    raise ValueError(f"unknown expect: {expect!r}")


def check_caveat(caveat: Caveat, *, control_ok: bool) -> dict:
    """Judge one caveat. `control_ok` gates STALE vs UNREACHABLE for its archive."""
    row = {
        "archive": caveat.archive,
        "caveat_id": caveat.caveat_id,
        "claim": caveat.claim,
        "expect": caveat.expect,
        "source": caveat.source,
    }
    if caveat.expect == "manual":
        return {**row, "status": "manual", "detail": "not auto-probeable — verify by hand"}
    archive = by_short_name(caveat.archive)
    endpoint = archive.tap_url if archive else None
    if not endpoint:
        return {**row, "status": "unreachable", "detail": "no tap_url for archive"}
    if not control_ok:
        return {**row, "status": "unreachable", "detail": "archive control probe failed"}

    outcome, n_rows, vals, detail = _probe(TapClient(), endpoint, caveat.adql)
    if caveat.expect == "count":
        n_expected = len(caveat.columns)
        if outcome == "service_error":
            status = "unreachable"  # transient — can't judge which columns are present
        elif outcome != "ok":
            status = "stale"
        elif n_rows == n_expected:
            status = "still_true"
        else:
            status = "stale"
            missing = [c for c in caveat.columns if c not in set(vals)]
            detail = (
                f"missing columns: {missing}" if missing else f"expected {n_expected}, got {n_rows}"
            )
    else:
        status = _verdict(caveat.expect, outcome, n_rows)
    return {**row, "status": status, "outcome": outcome, "n_rows": n_rows, "detail": detail}


def _control_ok(endpoint: str, control_adql: str) -> bool:
    outcome, _, _, _ = _probe(TapClient(), endpoint, control_adql)
    return outcome == "ok"


def run(caveats: tuple[Caveat, ...], *, workers: int = 8) -> list[dict]:
    """Run every caveat: one control probe per archive, then each caveat, concurrently."""
    # One liveness control per archive that has at least one probeable (non-manual) caveat.
    archives: dict[tuple[str, str], str] = {}
    for cv in caveats:
        if cv.expect == "manual":
            continue
        a = by_short_name(cv.archive)
        if a and a.tap_url:
            archives[(cv.archive, cv.control_adql)] = a.tap_url
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        control = dict(
            zip(
                archives,
                ex.map(lambda kv: _control_ok(kv[1], kv[0][1]), archives.items()),
                strict=True,
            )
        )
        rows = list(
            ex.map(
                lambda cv: check_caveat(
                    cv, control_ok=control.get((cv.archive, cv.control_adql), False)
                ),
                caveats,
            )
        )
    return rows


def _print(rows: list[dict], *, probeable_only: bool = False) -> None:
    print("\nArchive-caveat regression\n" + "=" * 78)
    by_arch: dict[str, list[dict]] = {}
    for r in rows:
        by_arch.setdefault(r["archive"], []).append(r)
    for arch, rs in by_arch.items():
        shown = [r for r in rs if not (probeable_only and r["status"] == "manual")]
        if not shown:
            continue
        print(f"\n{arch}")
        for r in shown:
            print(f"  [{_STATUS[r['status']]}] {r['caveat_id']:30s} {r['claim'][:56]}")
            if r["status"] in ("stale", "unreachable") and r.get("detail"):
                print(f"                  ↳ {r['detail'][:110]}")
                if r.get("source"):
                    print(f"                  ↳ update: {r['source']}")
    counts = {k: sum(r["status"] == k for r in rows) for k in _STATUS}
    print("\n" + "-" * 78)
    print(
        f"  {counts['still_true']} still-true   {counts['stale']} STALE   "
        f"{counts['unreachable']} unreachable   {counts['manual']} manual   "
        f"({len(rows)} caveats)"
    )
    if counts["stale"]:
        print("  ⚠ STALE caveats mean the archive changed — update the KB at the printed source.")


def main() -> int:
    p = argparse.ArgumentParser(description="Archive-caveat regression suite (model-free).")
    p.add_argument("--archive", help="only check one archive's caveats (short_name)")
    p.add_argument("--list", action="store_true", help="list caveats and exit (no probes)")
    p.add_argument("--probeable", action="store_true", help="hide MANUAL rows in the report")
    args = p.parse_args()

    caveats = CAVEATS
    if args.archive:
        caveats = tuple(c for c in caveats if c.archive == args.archive)
        if not caveats:
            print(f"no caveats for archive {args.archive!r}")
            return 2
    if args.list:
        for c in caveats:
            kind = c.expect if c.expect != "manual" else "MANUAL"
            print(f"  {c.archive:9s} {c.caveat_id:32s} {kind:8s} {c.claim[:48]}")
        print(
            f"\n  {len(caveats)} caveats "
            f"({sum(c.expect != 'manual' for c in caveats)} probeable, "
            f"{sum(c.expect == 'manual' for c in caveats)} manual)"
        )
        return 0

    probeable = sum(c.expect != "manual" for c in caveats)
    print(f"probing {probeable} caveats against live archives ({len(caveats)} total) …")
    rows = run(caveats)
    _print(rows, probeable_only=args.probeable)

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    out = RESULTS_DIR / f"caveats-{stamp}.json"
    out.write_text(json.dumps({"timestamp": stamp, "rows": rows}, indent=2, default=str))
    print(f"\nWrote {out}")
    stale = sum(r["status"] == "stale" for r in rows)
    return 1 if stale else 0  # non-zero exit if any caveat went stale (CI-friendly)


if __name__ == "__main__":
    raise SystemExit(main())
