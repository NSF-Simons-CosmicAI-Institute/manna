"""Archive-note regression suite — Pillar 3, derived from the archive knowledge itself.

The server's value is its *curated knowledge* of archive quirks — now atomic `Note`s
carried directly on each `archives/<short_name>.py` `Archive` (its `usage_notes` and each
`Schema`'s `notes`), each paired with an `Audit` describing how to re-check it live. Those
claims are about live third-party archives that drift underneath us: a sync endpoint starts
accepting reads, a missing column reappears, an untranslated geometry function starts
working. When that happens the KB silently goes STALE and the server starts handing agents
wrong advice.

This suite is the guard. Unlike the retired hand-maintained `evals/caveats.py` list, it is
**derived**: it walks the active archives' notes directly, so a new archive or a new note
is audited automatically — there's no separate table to keep in sync. It aims for **1:1
coverage of every falsifiable quirk** in the KB, keyed to `(archive, note_id)`, so running
it singles out *which* note went stale:

  * STILL-TRUE   — the archive still behaves as the note says.
  * STALE        — the archive changed; the note's claim no longer holds → update the KB.
  * UNREACHABLE  — the archive (or the network) is down; can't judge this run.
  * MANUAL       — the quirk isn't checkable by a single ADQL probe (SIA/DataLink download
                   recipes, advisory naming conventions, async-only behaviours that would
                   make the suite slow/flaky). Listed for completeness — verify by hand.

Probeable notes are **model-free**: a deterministic probe with an expected outcome
(`ok` / `error` / `empty` / `nonempty` / `count`). `count` checks a group of columns from one
note's `Audit` and, on drift, names exactly which column disappeared.

Separating STALE from UNREACHABLE: each archive first runs a **control probe** (a query that
must work if the service is up). If the control fails, the whole archive is UNREACHABLE and
its notes are not judged — so a network blip is never misreported as "the KB went stale".

    uv run python -m evals.audit                 # check every note
    uv run python -m evals.audit --archive nrao  # just one archive's notes
    uv run python -m evals.audit --list          # list notes, run nothing
    uv run python -m evals.audit --probeable     # skip MANUAL rows in the report
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import time
from pathlib import Path

from astro_archives_mcp.archives import get_active_archives
from astro_archives_mcp.archives._audit import has_cols, has_table  # noqa: F401 (re-export)
from astro_archives_mcp.archives._model import Archive, Note
from astro_archives_mcp.backends.tap import TapClient
from astro_archives_mcp.errors import DalQueryError

RESULTS_DIR = Path(__file__).with_name("results")

# A query that must succeed if the service is up — the STALE-vs-UNREACHABLE discriminator.
# NRAO's /sync fails on obscore *reads* but tap_schema metadata works in sync (that asymmetry
# is itself a caveat), so a metadata probe is the right liveness control for every archive.
_CONTROL_ADQL = "SELECT TOP 1 table_name FROM tap_schema.tables"

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
                          NOT trustworthy for a success-expecting probe — could be
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
    # A service/network error means we can't judge a success-expecting note — but for an
    # error-expecting note (e.g. NRAO's sync 5xx, which IS a service error) it's confirmation.
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


def collect_audits(archives: tuple[Archive, ...]) -> list[tuple[Archive, Note]]:
    """Flat (archive, note) list for every usage_note + schema note in the set.

    Includes manual notes — the runner never probes them (`check_note` short-circuits
    on `expect == "manual"`), but `--list` needs the full set for completeness.
    """
    out: list[tuple[Archive, Note]] = []
    for a in archives:
        for n in a.usage_notes:
            out.append((a, n))
        for s in a.schemas:
            for n in s.notes:
                out.append((a, n))
    return out


def _source(archive: Archive, note: Note) -> str:
    return f"archives/{archive.short_name}.py :: {note.id}"


def check_note(archive: Archive, note: Note, *, control_ok: bool) -> dict:
    """Judge one note. `control_ok` gates STALE vs UNREACHABLE for its archive."""
    a = note.audit
    row = {
        "archive": archive.short_name,
        "note_id": note.id,
        "claim": note.text,
        "expect": a.expect,
        "source": _source(archive, note),
    }
    if a.expect == "manual":
        return {**row, "status": "manual", "detail": a.reason or "verify by hand"}
    endpoint = getattr(archive, "tap_url", None)
    if not endpoint:
        return {**row, "status": "unreachable", "detail": "no tap_url for archive"}
    if not control_ok:
        return {**row, "status": "unreachable", "detail": "archive control probe failed"}

    outcome, n_rows, vals, detail = _probe(TapClient(), endpoint, a.adql)
    if a.expect == "count":
        n_expected = len(a.columns)
        if outcome == "service_error":
            status = "unreachable"  # transient — can't judge which columns are present
        elif outcome != "ok":
            status = "stale"
        elif n_rows == n_expected:
            status = "still_true"
        else:
            status = "stale"
            missing = [c for c in a.columns if c not in set(vals)]
            detail = (
                f"missing columns: {missing}" if missing else f"expected {n_expected}, got {n_rows}"
            )
    else:
        status = _verdict(a.expect, outcome, n_rows)
    return {**row, "status": status, "outcome": outcome, "n_rows": n_rows, "detail": detail}


def _control_ok(endpoint: str, control_adql: str) -> bool:
    outcome, _, _, _ = _probe(TapClient(), endpoint, control_adql)
    return outcome == "ok"


def run(archives: tuple[Archive, ...] | None = None, *, workers: int = 8) -> list[dict]:
    """Run every note: one control probe per archive, then each note, concurrently."""
    if archives is None:
        archives = get_active_archives()
    notes = collect_audits(archives)

    # One liveness control per archive that has at least one probeable (non-manual) note.
    control_endpoints: dict[str, str] = {}
    for a in archives:
        all_notes = (*a.usage_notes, *(n for s in a.schemas for n in s.notes))
        if a.tap_url and any(n.audit.expect != "manual" for n in all_notes):
            control_endpoints[a.short_name] = a.tap_url

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        control = dict(
            zip(
                control_endpoints,
                ex.map(lambda url: _control_ok(url, _CONTROL_ADQL), control_endpoints.values()),
                strict=True,
            )
        )
        rows = list(
            ex.map(
                lambda an: check_note(
                    an[0], an[1], control_ok=control.get(an[0].short_name, False)
                ),
                notes,
            )
        )
    return rows


def _print(rows: list[dict], *, probeable_only: bool = False) -> None:
    print("\nArchive-note regression\n" + "=" * 78)
    by_arch: dict[str, list[dict]] = {}
    for r in rows:
        by_arch.setdefault(r["archive"], []).append(r)
    for arch, rs in by_arch.items():
        shown = [r for r in rs if not (probeable_only and r["status"] == "manual")]
        if not shown:
            continue
        print(f"\n{arch}")
        for r in shown:
            print(f"  [{_STATUS[r['status']]}] {r['note_id']:30s} {r['claim'][:56]}")
            if r["status"] in ("stale", "unreachable") and r.get("detail"):
                print(f"                  ↳ {r['detail'][:110]}")
                if r.get("source"):
                    print(f"                  ↳ update: {r['source']}")
    counts = {k: sum(r["status"] == k for r in rows) for k in _STATUS}
    print("\n" + "-" * 78)
    print(
        f"  {counts['still_true']} still-true   {counts['stale']} STALE   "
        f"{counts['unreachable']} unreachable   {counts['manual']} manual   "
        f"({len(rows)} notes)"
    )
    if counts["stale"]:
        print("  ⚠ STALE notes mean the archive changed — update the KB at the printed source.")


def main() -> int:
    p = argparse.ArgumentParser(description="Archive-note regression suite (model-free).")
    p.add_argument("--archive", help="only check one archive's notes (short_name)")
    p.add_argument("--list", action="store_true", help="list notes and exit (no probes)")
    p.add_argument("--probeable", action="store_true", help="hide MANUAL rows in the report")
    args = p.parse_args()

    archives = get_active_archives()
    if args.archive:
        archives = tuple(a for a in archives if a.short_name == args.archive)
        if not archives:
            print(f"no archive {args.archive!r} in the active set")
            return 2

    notes = collect_audits(archives)
    if args.list:
        for a, n in notes:
            kind = n.audit.expect if n.audit.expect != "manual" else "MANUAL"
            print(f"  {a.short_name:9s} {n.id:32s} {kind:8s} {n.text[:48]}")
        print(
            f"\n  {len(notes)} notes "
            f"({sum(n.audit.expect != 'manual' for _, n in notes)} probeable, "
            f"{sum(n.audit.expect == 'manual' for _, n in notes)} manual)"
        )
        return 0

    probeable = sum(n.audit.expect != "manual" for _, n in notes)
    print(f"probing {probeable} notes against live archives ({len(notes)} total) …")
    rows = run(archives)
    _print(rows, probeable_only=args.probeable)

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    out = RESULTS_DIR / f"audit-{stamp}.json"
    out.write_text(json.dumps({"timestamp": stamp, "rows": rows}, indent=2, default=str))
    print(f"\nWrote {out}")
    stale = sum(r["status"] == "stale" for r in rows)
    return 1 if stale else 0  # non-zero exit if any note went stale (CI-friendly)


if __name__ == "__main__":
    raise SystemExit(main())
