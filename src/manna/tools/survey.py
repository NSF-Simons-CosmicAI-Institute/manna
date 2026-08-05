"""Multi-archive availability facade: vo_survey_target.

"What data exists for this target, everywhere?" — resolves the target once,
then fans the curated per-archive count out over every countable archive and
aggregates the results. An aggregator over vo_count_observations' substrate;
per-archive failures are isolated into a row status, never a hard failure.
"""

from typing import Annotated

from pydantic import Field

from manna.archives._count import build_count_adql
from manna.errors import ToolExecutionError, ValidationError, wrap_tool_errors
from manna.tools import _select
from manna.tools._constants import _ERROR_DOCSTRING
from manna.tools.count import _run_count


@wrap_tool_errors
def vo_survey_target(
    target: Annotated[
        str,
        Field(
            description=(
                "Object name (Sesame-resolved) or explicit ICRS 'RA DEC' in decimal degrees."
            ),
            examples=["M87", "NGC 253"],
        ),
    ],
    radius_deg: Annotated[
        float, Field(ge=0.0001, le=5.0, description="Search radius in degrees. Default 0.1.")
    ] = 0.1,
    wavebands: Annotated[
        list[str] | None,
        Field(
            # An empty list is treated the same as None (no filter, all
            # countable archives) — the safe default rather than "match
            # nothing".
            description="Optional list of wavebands to restrict the fan-out.",
            examples=[["radio", "optical"]],
        ),
    ] = None,
) -> dict:
    """Survey which archives hold data for a target, with per-archive counts.

    Resolves the target, then runs each countable archive's curated positional
    COUNT and returns one row per archive: {archive, display_name, waveband,
    table, count, status, [job_url, next_steps]}. `status` ∈ {ok, pending,
    error} is always explicit — never a silent zero. A `summary` block totals
    archives_with_data / wavebands / pending / errors. Soft-fails (no
    error_class) on an unresolvable target. For a single archive with finer
    control, drop to vo_count_observations or vo_tap_query.
    """
    target_clean = target.strip()
    if not target_clean:
        raise ValidationError(
            message="'target' must be non-empty. Provide an object name or 'RA DEC'."
        )

    ra, dec = _select.coerce_or_resolve(target_clean)
    if ra is None or dec is None:
        return {
            "resolved": False,
            "target": target_clean,
            "message": "Could not resolve target; pass explicit 'RA DEC'.",
        }

    wb_filter = {w.strip().lower() for w in wavebands} if wavebands else None
    archives = [a for a in _select.active_archives() if a.count_target]
    if wb_filter is not None:
        archives = [a for a in archives if (a.waveband or "").lower() in wb_filter]

    rows: list[dict] = []
    # Sequential by design: each backend call is a blocking pyvo round-trip, so
    # worst-case latency here is the SUM of every archive's async count budget,
    # not the max. Parallelizing would need threads (pyvo has no async client).
    for a in archives:
        ct = a.count_target
        assert ct is not None and a.tap_url is not None
        row = {
            "archive": a.short_name,
            "display_name": a.display_name,
            "waveband": a.waveband,
            "table": ct.table,
        }
        try:
            adql = build_count_adql(ct, ra, dec, radius_deg)
            res = _run_count(endpoint=a.tap_url, adql=adql, mode=ct.mode)
            if res["status"] == "pending":
                row.update(
                    status="pending",
                    count=None,
                    job_url=res["job_url"],
                    next_steps=(
                        f"The count is running async as job_url='{res['job_url']}'. Poll "
                        f"vo_tap_status(job_url='{res['job_url']}') until phase=COMPLETED, "
                        f"then vo_tap_results(job_url='{res['job_url']}') for the single "
                        f"count row. Pass the job_url back verbatim — it is the job's only "
                        f"handle."
                    ),
                )
            else:
                row.update(status="ok", count=res["count"])
        except ToolExecutionError as err:
            row.update(status="error", count=None, error=err.message)
        rows.append(row)

    with_data = sum(1 for r in rows if r.get("status") == "ok" and (r.get("count") or 0) > 0)
    return {
        "resolved": {"target": target_clean, "ra": ra, "dec": dec, "frame": "icrs"},
        "radius_deg": radius_deg,
        "archives": rows,
        "summary": {
            "archives_queried": len(rows),
            "archives_with_data": with_data,
            "wavebands": sorted(
                {
                    r["waveband"]
                    for r in rows
                    if r.get("status") == "ok" and (r.get("count") or 0) > 0 and r["waveband"]
                }
            ),
            "pending": sum(1 for r in rows if r.get("status") == "pending"),
            "errors": sum(1 for r in rows if r.get("status") == "error"),
        },
    }


vo_survey_target.__doc__ = (vo_survey_target.__doc__ or "") + _ERROR_DOCSTRING
