"""Archive-caveat regression suite — Pillar 3.

The server's value is its *curated knowledge* of archive quirks (`known_archives.py`
usage_notes, `schema_kb.py` facts). Those claims are about live third-party archives that
drift underneath us: a sync endpoint starts accepting reads, a missing column reappears, an
untranslated geometry function starts working. When that happens the KB silently goes STALE
and the server starts handing agents wrong advice.

This suite is a **model-free** guard: one small live probe per falsifiable caveat, keyed to
`(archive, caveat_id)`, that re-checks the claim against the real archive and reports:

  * STILL-TRUE   — the archive still behaves as the KB says.
  * STALE        — the archive changed; the KB claim no longer holds → update the KB.
  * UNREACHABLE  — the archive (or the network) is down; can't judge this run.

No LLM is involved — each caveat is a deterministic ADQL probe with an expected outcome.

Separating STALE from UNREACHABLE: each archive first runs a **control probe** (a query that
must work if the service is up). If the control fails, the whole archive is UNREACHABLE and
its caveats are not judged — so a network blip is never misreported as "the KB went stale".
Only when the control passes do we trust a caveat probe that behaves opposite to its claim.

    uv run python -m evals.caveats                 # check every caveat
    uv run python -m evals.caveats --archive nrao  # just one archive's caveats
    uv run python -m evals.caveats --list          # list caveats, run nothing
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import time
from dataclasses import dataclass
from pathlib import Path

from astro_archives_mcp.backends.tap import TapClient
from astro_archives_mcp.errors import ArchiveError, DalQueryError
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
    adql: str  # the probe query
    expect: str  # "ok" (must succeed) | "error" (must fail) | "empty" (succeed, 0 rows)
    control_adql: str = _CONTROL_ADQL  # liveness probe for this caveat's archive


# --------------------------------------------------------------------------- #
# The caveats — each maps to a specific line in known_archives.py usage_notes.
# Only cleanly sync-probeable, unambiguous claims are encoded here.
# --------------------------------------------------------------------------- #
CAVEATS: tuple[Caveat, ...] = (
    # -- NOIRLab Astro Data Lab -------------------------------------------------
    Caveat(
        "datalab",
        "geometry-untranslated",
        "CONTAINS(POINT(...),CIRCLE(...)) is NOT translated and fails "
        "('function point(...) does not exist').",
        "SELECT TOP 1 ra, dec FROM nsc_dr2.object "
        "WHERE CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', 10.0, 10.0, 0.01)) = 1",
        expect="error",
    ),
    Caveat(
        "datalab",
        "q3c-literal-ok",
        "An indexed cone uses q3c_radial_query(...) = 't' (the ='t' literal is required).",
        "SELECT TOP 1 ra, dec FROM nsc_dr2.object "
        "WHERE q3c_radial_query(ra, dec, 10.0, 10.0, 0.01) = 't'",
        expect="ok",
    ),
    # -- NRAO -------------------------------------------------------------------
    Caveat(
        "nrao",
        "sync-5xx-on-obscore",
        "The /sync endpoint returns 5xx on reads against tap_schema.obscore (even SELECT TOP 1).",
        "SELECT TOP 1 * FROM tap_schema.obscore",
        expect="error",
    ),
    Caveat(
        "nrao",
        "obscore-nonstandard-location",
        "ObsCore lives at tap_schema.obscore, NOT the standard ivoa.obscore "
        "(so ivoa.obscore is absent from the schema).",
        "SELECT TOP 1 table_name FROM tap_schema.tables WHERE table_name = 'ivoa.obscore'",
        expect="empty",
    ),
    Caveat(
        "nrao",
        "no-dataproduct-subtype",
        "The standard ObsCore column dataproduct_subtype is ABSENT from NRAO's tap_schema.obscore.",
        "SELECT TOP 1 column_name FROM tap_schema.columns "
        "WHERE table_name = 'tap_schema.obscore' AND column_name = 'dataproduct_subtype'",
        expect="empty",
    ),
    # -- ALMA -------------------------------------------------------------------
    Caveat(
        "alma",
        "sync-spatial-ok",
        "Spatial filters (INTERSECTS on s_region) work directly in /sync — no async needed.",
        "SELECT TOP 1 s_ra, s_dec FROM ivoa.obscore "
        "WHERE INTERSECTS(CIRCLE('ICRS', 201.365, -43.019, 0.05), s_region) = 1",
        expect="ok",
    ),
    # -- Gaia -------------------------------------------------------------------
    Caveat(
        "gaia",
        "dr3-default-table",
        "gaiadr3.gaia_source is the default, present table.",
        "SELECT TOP 1 source_id FROM gaiadr3.gaia_source",
        expect="ok",
    ),
    # -- ESO --------------------------------------------------------------------
    Caveat(
        "eso",
        "obscore-mixedcase",
        "ESO exposes ObsCore at the mixed-case ivoa.ObsCore table.",
        "SELECT TOP 1 * FROM ivoa.ObsCore",
        expect="ok",
    ),
    # -- CADC -------------------------------------------------------------------
    Caveat(
        "cadc",
        "tap-reachable",
        "CADC TAP serves the ObsCore/caom2 tables (baseline reachability for the "
        "SIA2/DataLink download caveats, which aren't TAP-probeable).",
        "SELECT TOP 1 * FROM caom2.Observation",
        expect="ok",
    ),
)

_STATUS = {"still_true": "STILL-TRUE ", "stale": "  STALE   ", "unreachable": "UNREACHABLE"}


def _probe(client: TapClient, endpoint: str, adql: str) -> tuple[str, int, str]:
    """Run one probe. Returns (outcome, n_rows, detail) where outcome ∈ ok|error."""
    try:
        table = client.query(endpoint=endpoint, adql=adql, maxrec=1)
    except (DalQueryError, ArchiveError) as exc:
        return "error", 0, f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # anything unexpected still counts as a failed probe
        return "error", 0, f"{type(exc).__name__}: {exc}"
    return "ok", len(table), ""


def _verdict(expect: str, outcome: str, n_rows: int) -> str:
    """Given the claim's expectation and the observed probe outcome, classify."""
    if expect == "ok":
        return "still_true" if outcome == "ok" else "stale"
    if expect == "error":
        return "still_true" if outcome == "error" else "stale"
    if expect == "empty":  # claim: query succeeds but returns nothing (absence)
        if outcome != "ok":
            return "stale"  # control passed, yet a metadata probe errors → schema changed
        return "still_true" if n_rows == 0 else "stale"
    raise ValueError(f"unknown expect: {expect!r}")


def check_caveat(caveat: Caveat, *, control_ok: bool) -> dict:
    """Judge one caveat. `control_ok` gates STALE vs UNREACHABLE for its archive."""
    archive = by_short_name(caveat.archive)
    endpoint = archive.tap_url if archive else None
    row = {
        "archive": caveat.archive,
        "caveat_id": caveat.caveat_id,
        "claim": caveat.claim,
        "expect": caveat.expect,
    }
    if not endpoint:
        return {**row, "status": "unreachable", "detail": "no tap_url for archive"}
    if not control_ok:
        return {**row, "status": "unreachable", "detail": "archive control probe failed"}
    outcome, n_rows, detail = _probe(TapClient(), endpoint, caveat.adql)
    return {
        **row,
        "status": _verdict(caveat.expect, outcome, n_rows),
        "outcome": outcome,
        "n_rows": n_rows,
        "detail": detail,
    }


def _control_ok(endpoint: str, control_adql: str) -> bool:
    outcome, _, _ = _probe(TapClient(), endpoint, control_adql)
    return outcome == "ok"


def run(caveats: tuple[Caveat, ...], *, workers: int = 6) -> list[dict]:
    """Run every caveat: one control probe per archive, then each caveat, concurrently."""
    # One liveness control per (archive, control_adql) pair — don't re-probe per caveat.
    archives = {}
    for cv in caveats:
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


def _print(rows: list[dict]) -> None:
    print("\nArchive-caveat regression\n" + "=" * 72)
    by_arch: dict[str, list[dict]] = {}
    for r in rows:
        by_arch.setdefault(r["archive"], []).append(r)
    for arch, rs in by_arch.items():
        print(f"\n{arch}")
        for r in rs:
            line = f"  [{_STATUS[r['status']]}] {r['caveat_id']:28s} {r['claim'][:60]}"
            print(line)
            if r["status"] != "still_true" and r.get("detail"):
                print(f"                 ↳ {r['detail'][:100]}")
    counts = {k: sum(r["status"] == k for r in rows) for k in _STATUS}
    print("\n" + "-" * 72)
    print(
        f"  {counts['still_true']} still-true   {counts['stale']} STALE   "
        f"{counts['unreachable']} unreachable   ({len(rows)} caveats)"
    )
    if counts["stale"]:
        print("  ⚠ STALE caveats mean the archive changed — update the KB (known_archives.py).")


def main() -> int:
    p = argparse.ArgumentParser(description="Archive-caveat regression suite (model-free).")
    p.add_argument("--archive", help="only check one archive's caveats (short_name)")
    p.add_argument("--list", action="store_true", help="list caveats and exit (no probes)")
    args = p.parse_args()

    caveats = CAVEATS
    if args.archive:
        caveats = tuple(c for c in caveats if c.archive == args.archive)
        if not caveats:
            print(f"no caveats for archive {args.archive!r}")
            return 2
    if args.list:
        for c in caveats:
            print(f"  {c.archive:9s} {c.caveat_id:28s} expect={c.expect:6s} {c.claim[:50]}")
        return 0

    print(f"probing {len(caveats)} caveats against live archives …")
    rows = run(caveats)
    _print(rows)

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    out = RESULTS_DIR / f"caveats-{stamp}.json"
    out.write_text(json.dumps({"timestamp": stamp, "rows": rows}, indent=2, default=str))
    print(f"\nWrote {out}")
    stale = sum(r["status"] == "stale" for r in rows)
    return 1 if stale else 0  # non-zero exit if any caveat went stale (CI-friendly)


if __name__ == "__main__":
    raise SystemExit(main())
