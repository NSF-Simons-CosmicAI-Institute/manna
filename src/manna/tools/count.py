"""Purpose-driven counting facade: vo_count_observations.

One call answers "how many observations/sources are near this target?" by
resolving the target, selecting an archive by its curated `count_target`, and
running the archive-correct positional COUNT — sync, or (NRAO) async with a
bounded poll. A thin facade over TapClient + the resolver; the atomic
vo_tap_query stays the escape hatch (the chosen ADQL is surfaced in `plan`).
"""

import time
from typing import Annotated

from pydantic import Field

from manna.archives._count import build_count_adql
from manna.archives._model import note_texts
from manna.backends.tap import TapClient
from manna.config import get_settings
from manna.errors import (
    ArchiveError,
    TimeoutArchiveError,
    ValidationError,
    wrap_tool_errors,
)
from manna.tools import _select
from manna.tools._constants import _ERROR_DOCSTRING

_tap: TapClient | None = None
_sleep = time.sleep  # module-level so tests can patch it


def _get_tap() -> TapClient:
    global _tap
    if _tap is None:
        _tap = TapClient(sync_timeout_seconds=get_settings().tap_sync_timeout_seconds)
    return _tap


def _extract_count(table) -> int:
    """The single COUNT value from a one-row result (aliased `n`)."""
    return int(table[0][0])


def _run_count(*, endpoint: str, adql: str, mode: str) -> dict:
    """Execute a count. Returns {status, count, job_url}.

    status: 'ok' (count set) | 'pending' (async budget exhausted; job_url set)
    Raises through wrap_tool_errors on a genuine sync error in sync/auto modes.
    """
    tap = _get_tap()
    if mode in ("sync", "auto"):
        try:
            table = tap.query(endpoint=endpoint, adql=adql, maxrec=1)
            return {"status": "ok", "count": _extract_count(table), "job_url": None}
        except TimeoutArchiveError:
            if mode == "sync":
                raise
            # auto: fall through to async
    return _run_count_async(endpoint=endpoint, adql=adql)


def _run_count_async(*, endpoint: str, adql: str) -> dict:
    s = get_settings()
    budget = s.count_async_budget_seconds
    interval = s.count_async_poll_interval_seconds
    tap = _get_tap()
    job_url = tap.submit_async(endpoint=endpoint, adql=adql, maxrec=1)

    waited = 0.0
    while waited < budget:
        job = tap.load_job(job_url)
        phase = job.phase
        if phase == "COMPLETED":
            job.raise_if_error()
            table = job.fetch_result().to_table()
            return {"status": "ok", "count": _extract_count(table), "job_url": None}
        if phase in ("ERROR", "ABORTED"):
            raise ArchiveError(
                message=f"async count job ended in phase {phase}",
                retry_strategy="wait_and_retry",
            )
        _sleep(interval)
        waited += interval

    # Budget exhausted — nothing is recorded server-side (no JobStore, see
    # config.py / shape_promotion): the returned job_url is the whole handle,
    # same contract as vo_tap_query's async promotion.
    return {"status": "pending", "count": None, "job_url": job_url}


@wrap_tool_errors
def vo_count_observations(
    target: Annotated[
        str,
        Field(
            description=(
                "Object name (CDS Sesame-resolved — 'M87', 'Cygnus A') OR explicit "
                "ICRS 'RA DEC' in decimal degrees ('187.7059 12.3911', comma optional). "
                "You do NOT need to call vo_target_resolve first."
            ),
            examples=["M87", "200.0 20.0"],
        ),
    ],
    radius_deg: Annotated[
        float, Field(ge=0.0001, le=5.0, description="Search radius in degrees. Default 0.1.")
    ] = 0.1,
    waveband: Annotated[
        str | None,
        Field(
            description=(
                "Optional waveband to steer archive choice — 'radio', 'optical', "
                "'millimeter'. Omit to use the highest-priority countable archive."
            ),
            examples=["radio", "optical"],
        ),
    ] = None,
    archive: Annotated[
        str | None,
        Field(
            description="Optional short_name override ('nrao', 'datalab') to skip auto-selection.",
            examples=["nrao", "datalab"],
        ),
    ] = None,
) -> dict:
    """Count observations/sources near a target in one call (resolve -> select -> COUNT).

    Selects an archive by its curated `count_target` and runs the
    archive-correct positional COUNT: q3c for Data Lab, CONTAINS/CIRCLE for
    Gaia/ESO/NRAO obscore, INTERSECTS + COUNT(DISTINCT member_ous_uid) for
    ALMA. NRAO runs async with a bounded poll.

    Returns `count` (int) plus a `resolved` block and a `plan` block
    (chosen_archive, table, endpoint, adql, count_expr, mode, alternatives,
    usage_notes). If a slow async job outruns the poll budget, returns
    `{"status":"pending","count":null,"job_url":...,"next_steps":...}` — poll
    vo_tap_status(job_url) until phase=COMPLETED, then vo_tap_results(job_url).
    Pass job_url back verbatim; it is the job's only handle (no server-side
    job id). Soft-fails (no error_class) on an unresolvable target or when no
    archive offers counting.
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
            "message": (
                "Could not resolve target via CDS Sesame. Try an alternate "
                "designation, or pass explicit 'RA DEC' in decimal degrees."
            ),
        }

    candidates = _select.rank_by_attr(attr="count_target", waveband=waveband, override=archive)
    if not candidates:
        return _select.no_candidate_payload(
            attr="count_target",
            service_label="counting",
            waveband=waveband,
            override=archive,
            servicetype="tap",
        )

    chosen = candidates[0]
    ct = chosen.count_target
    assert ct is not None and chosen.tap_url is not None
    adql = build_count_adql(ct, ra, dec, radius_deg)
    result = _run_count(endpoint=chosen.tap_url, adql=adql, mode=ct.mode)

    plan = {
        "chosen_archive": chosen.short_name,
        "table": ct.table,
        "endpoint": chosen.tap_url,
        "adql": adql,
        "count_expr": ct.count_expr,
        "mode": ct.mode,
        "alternatives": [c.short_name for c in candidates[1:3]] or None,
        "usage_notes": note_texts(chosen.usage_notes) or None,
    }
    resolved = {"target": target_clean, "ra": ra, "dec": dec, "frame": "icrs"}

    if result["status"] == "pending":
        return {
            "status": "pending",
            "count": None,
            "job_url": result["job_url"],
            "resolved": resolved,
            "plan": plan,
            "next_steps": (
                f"The count is running async as job_url='{result['job_url']}'. Poll "
                f"vo_tap_status(job_url='{result['job_url']}') until phase=COMPLETED, "
                f"then vo_tap_results(job_url='{result['job_url']}') for the single "
                f"count row. Pass the job_url back verbatim — it is the job's only "
                f"handle."
            ),
        }

    return {"status": "ok", "count": result["count"], "resolved": resolved, "plan": plan}


vo_count_observations.__doc__ = (vo_count_observations.__doc__ or "") + _ERROR_DOCSTRING
