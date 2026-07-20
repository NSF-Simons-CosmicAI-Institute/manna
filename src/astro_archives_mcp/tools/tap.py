"""Tools for IVOA TAP."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import Field

from astro_archives_mcp import job_store
from astro_archives_mcp._archive_label import archive_label
from astro_archives_mcp.archives._endpoints import (
    tap_endpoint_description,
    tap_endpoint_urls,
)
from astro_archives_mcp.archives._traps import loud_trap_guidance
from astro_archives_mcp.backends.tap import TapClient
from astro_archives_mcp.config import get_settings
from astro_archives_mcp.errors import (
    ArchiveError,
    DalQueryError,
    JobNotReadyError,
    TimeoutArchiveError,
    ValidationError,
    wrap_tool_errors,
)
from astro_archives_mcp.shaper import (
    is_oversize,
    shape_inline_table,
    shape_promotion,
    shape_result_url,
)
from astro_archives_mcp.tools._constants import _ERROR_DOCSTRING

_tap: TapClient | None = None


def _get_tap() -> TapClient:
    """Lazy accessor so tests can patch TapClient without import-time side effects."""
    global _tap
    if _tap is None:
        _tap = TapClient(
            sync_timeout_seconds=get_settings().tap_sync_timeout_seconds,
        )
    return _tap


@contextmanager
def _trap_hint(*, endpoint: str, adql: str) -> Iterator[None]:
    """Attach curated loud-trap guidance to a rejected query's `hint`.

    The error payload is the one channel the model reliably reads at failure
    time — issue #57 measured it writing LOWER() against NRAO even with the
    note served by vo_archive_list. So when the archive rejects an ADQL that
    trips a curated loud trap, the fix rides back with the rejection.

    Only DalQueryError: that means the archive UNDERSTOOD the query and refused
    it, which is when curated guidance is trustworthy. A timeout or 5xx says
    nothing about the ADQL. An existing hint is never overwritten.
    """
    try:
        yield
    except DalQueryError as err:
        if err.hint is None:
            err.hint = loud_trap_guidance(archive_label(endpoint), adql)
        raise


def _promote_async(*, endpoint: str, adql: str, maxrec: int) -> dict:
    """Submit async and return a promotion envelope.

    Wraps submit + JobStore put + envelope shaping. Raises ArchiveError
    if the async submission itself fails (so the caller still gets a
    structured payload via wrap_tool_errors).
    """
    job_url = _get_tap().submit_async(endpoint=endpoint, adql=adql, maxrec=maxrec)
    job_id, _ = job_store.put(
        job_url=job_url,
        endpoint=endpoint,
        adql=adql,
        ttl_seconds=get_settings().job_ttl_seconds,
    )
    return shape_promotion(
        job_id=job_id,
        job_url=job_url,
        archive=archive_label(endpoint),
        phase="EXECUTING",
        submitted_at=datetime.now(UTC),
    )


def _auto_promote(*, endpoint: str, adql: str, maxrec: int) -> dict:
    """Promote to async from the mode='auto' path (timeout or oversize).

    Wraps a submission failure in a friendlier archive_error so the LLM
    gets a coherent retry signal rather than a raw submit error.
    """
    try:
        return _promote_async(endpoint=endpoint, adql=adql, maxrec=maxrec)
    except ArchiveError as submit_err:
        raise ArchiveError(
            message=f"auto-promote submission failed: {submit_err.message}",
            retry_strategy="wait_and_retry",
        ) from submit_err


@wrap_tool_errors
def vo_tap_query(
    endpoint: Annotated[
        str,
        Field(
            description=tap_endpoint_description(),
            examples=tap_endpoint_urls()[:2],
        ),
    ],
    adql: Annotated[
        str,
        Field(
            description=(
                "ADQL query. Geometry support is archive-specific: standard "
                "CIRCLE/POINT/CONTAINS work on obscore services (ALMA, NRAO) but "
                "NOT on Astro Data Lab, which passes them to PostgreSQL and needs "
                "q3c_radial_query(...) = 't' instead — call vo_archive_list for the "
                "archive's quirks before composing. Use SELECT TOP N to cap row "
                "counts, project an explicit column list rather than SELECT * "
                "(vo_schema_describe returns the table's real columns), and ORDER BY "
                "for deterministic results."
            ),
            examples=[
                # Data Lab: ADQL geometry is NOT translated (it reaches PostgreSQL
                # as-is and errors). Verified live 2026-07-15: returns 100 rows.
                "SELECT TOP 100 ra, dec, gmag FROM smash_dr2.object "
                "WHERE q3c_radial_query(ra, dec, 185.43, -31.99, 0.2) = 't'",
                # obscore services DO support standard ADQL geometry.
                "SELECT TOP 100 obs_id, s_ra, s_dec FROM ivoa.obscore "
                "WHERE CONTAINS(POINT('ICRS', s_ra, s_dec), "
                "CIRCLE('ICRS', 187.7, 12.39, 0.1)) = 1",
            ],
        ),
    ],
    maxrec: Annotated[
        int,
        Field(
            ge=1,
            le=100_000,
            description="Hard cap on rows returned. Default 10_000.",
        ),
    ] = 10_000,
    mode: Annotated[
        Literal["sync", "async", "auto"],
        Field(
            description=(
                "Execution mode. 'sync' = TAP /sync only (default Slice-A "
                "behavior; times out as archive_error). 'async' = skip "
                "sync, submit /async, return a promotion envelope with "
                "job_id. 'auto' (default) = try sync first; on timeout, "
                "transparently promote to async."
            ),
        ),
    ] = "auto",
) -> dict:
    """Run an ADQL query against any IVOA-compliant TAP service.

    BEFORE composing a query against an archive you don't already know
    cold, call `vo_archive_list` first. It returns curated usage notes
    for the well-known archives — non-standard table locations, required
    mode='async' routing, ADQL quirks, target-name conventions — that
    will save you trial-and-error here.

    The server never holds result bytes. Small results come back inline;
    anything larger than the inline cap is routed to an async job whose
    result the client fetches itself (see vo_tap_results / fetch_recipe).

    Returns one of two envelope shapes depending on what happened:

    1. Inline result envelope (row_count, columns, rows).
       Returned when the result fits the inline cap: mode='sync' with a
       small result, or mode='auto' when the query finished within the
       sync timeout AND fit inline. No `mode` key on the response.

    2. Promotion envelope (mode='async', job_id, job_url, fetch_recipe).
       Returned when mode='async', when mode='auto' and the sync attempt
       timed out, or when mode='auto' and the sync result was too large
       to inline. Disambiguate by checking payload.get('mode') == 'async'.

    mode='sync' with an oversize result does NOT auto-promote — it raises
    validation_error telling you to re-run with mode='async'.

    For async results, poll vo_tap_status(job_id) until phase is
    COMPLETED, then call vo_tap_results(job_id) — or fetch client-side
    with the pyvo fetch_recipe carried on the promotion envelope.
    """
    # Every path that can surface a DalQueryError runs inside _trap_hint, so a
    # rejected query carries its curated fix regardless of which mode found it.
    with _trap_hint(endpoint=endpoint, adql=adql):
        if mode == "async":
            return _promote_async(endpoint=endpoint, adql=adql, maxrec=maxrec)

        if mode == "sync":
            table = _get_tap().query(endpoint=endpoint, adql=adql, maxrec=maxrec)
            if is_oversize(table):
                raise ValidationError(
                    message=(
                        f"Result ({len(table)} rows) exceeds the inline cap. "
                        "Re-run vo_tap_query with mode='async' to get a job_url + "
                        "fetch_recipe for client-side loading."
                    ),
                    retry_strategy="fix_and_retry",
                )
            return shape_inline_table(table, archive=archive_label(endpoint), maxrec=maxrec)

        # mode == "auto": try sync, promote to async on a sync timeout OR when the
        # sync result is too large to inline. The timeout discriminator is the
        # exception TYPE (TimeoutArchiveError), not a substring — other archive
        # errors (unreachable host, 5xx) are plain ArchiveError and propagate.
        try:
            table = _get_tap().query(endpoint=endpoint, adql=adql, maxrec=maxrec)
        except TimeoutArchiveError:
            return _auto_promote(endpoint=endpoint, adql=adql, maxrec=maxrec)
        if is_oversize(table):
            # We already ran it once synchronously; re-submit as async so the
            # archive holds the bytes and we can hand back a fetch URL. The first
            # (discarded) execution is the cost of not knowing the size upfront.
            return _auto_promote(endpoint=endpoint, adql=adql, maxrec=maxrec)
        return shape_inline_table(table, archive=archive_label(endpoint), maxrec=maxrec)


vo_tap_query.__doc__ = (vo_tap_query.__doc__ or "") + _ERROR_DOCSTRING


def _status_payload(*, job_id: str, job, endpoint: str) -> dict:
    """Build the status response from a live AsyncTAPJob."""
    error_message = None
    if job.phase == "ERROR":
        es = getattr(job, "error_summary", None)
        if es is not None:
            error_message = getattr(es, "message", None) or str(es)

    started = getattr(job, "starttime", None)
    ended = getattr(job, "endtime", None)
    return {
        "job_id": job_id,
        "phase": job.phase,
        "started_at": started.isoformat() if started else None,
        "ended_at": ended.isoformat() if ended else None,
        "error_message": error_message,
        "archive": archive_label(endpoint),
    }


@wrap_tool_errors
def vo_tap_status(
    job_id: Annotated[
        str,
        Field(
            description=(
                "Opaque 12-character job_id returned by vo_tap_query "
                "when it goes async (mode='async' or auto-promote)."
            ),
            min_length=12,
            max_length=12,
        ),
    ],
) -> dict:
    """Fetch the live UWS phase for an async TAP job.

    Returns {job_id, phase, started_at, ended_at, error_message, archive}.
    Phase is read live from the upstream service; no local caching.

    Phases per UWS spec: PENDING, QUEUED, EXECUTING, COMPLETED, ERROR,
    ABORTED, ARCHIVED, HELD, SUSPENDED, UNKNOWN. The LLM branches on
    the string.
    """
    entry = job_store.get(job_id)
    if entry is None:
        raise ValidationError(
            message=(f"Unknown or expired job_id '{job_id}'. Re-submit with vo_tap_query."),
            retry_strategy="abandon",
        )
    job = _get_tap().load_job(entry.job_url)
    return _status_payload(job_id=job_id, job=job, endpoint=entry.endpoint)


vo_tap_status.__doc__ = (vo_tap_status.__doc__ or "") + _ERROR_DOCSTRING


@wrap_tool_errors
def vo_tap_results(
    job_id: Annotated[
        str,
        Field(
            description="Opaque 12-character job_id from vo_tap_query (async).",
            min_length=12,
            max_length=12,
        ),
    ],
) -> dict:
    """Return access info for a COMPLETED async TAP job.

    The server does NOT fetch the result bytes. It returns the upstream
    job_url, the direct result_url, and a pyvo fetch_recipe so the client
    loads the data itself (e.g. in a Jupyter kernel). Anonymous access
    only.

    If the job is not yet COMPLETED, raises job_not_ready (retry_strategy=poll).
    If the job ended in ERROR, raises tap_query_error with the upstream
    message.
    """
    entry = job_store.get(job_id)
    if entry is None:
        raise ValidationError(
            message=(f"Unknown or expired job_id '{job_id}'. Re-submit with vo_tap_query."),
            retry_strategy="abandon",
        )

    job = _get_tap().load_job(entry.job_url)
    phase = job.phase

    if phase == "ERROR":
        es = getattr(job, "error_summary", None)
        msg = getattr(es, "message", None) if es is not None else None
        raise DalQueryError(message=msg or "Async TAP job ended in ERROR.")
    if phase == "ABORTED":
        raise ValidationError(
            message=f"Job {job_id} was aborted; re-submit if you still want results.",
            retry_strategy="abandon",
        )
    if phase != "COMPLETED":
        raise JobNotReadyError(
            message=f"Job is still {phase}.",
            hint="Call vo_tap_status until phase is COMPLETED, then retry.",
        )

    # Read the direct result URL from the loaded job. It may be absent on
    # some services; the pyvo recipe (built from job_url) still works, so a
    # missing result_url is non-fatal.
    try:
        result_url = job.result_uri
    except Exception:  # noqa: BLE001 — pyvo attribute access is best-effort
        result_url = None
    # phase is necessarily "COMPLETED" here — every other phase returned or
    # raised above — so shape_result_url uses its "COMPLETED" default.
    return shape_result_url(
        job_url=entry.job_url,
        result_url=result_url,
        archive=archive_label(entry.endpoint),
    )


vo_tap_results.__doc__ = (vo_tap_results.__doc__ or "") + _ERROR_DOCSTRING


@wrap_tool_errors
def vo_tap_abort(
    job_id: Annotated[
        str,
        Field(
            description="Opaque 12-character job_id from vo_tap_query (async).",
            min_length=12,
            max_length=12,
        ),
    ],
) -> dict:
    """Cancel a running async TAP job.

    Sends UWS DELETE upstream and evicts the local JobStore entry.
    Idempotent: aborting an already-deleted or expired job returns the
    same {job_id, phase=ABORTED} shape rather than raising.
    """
    entry = job_store.get(job_id)
    if entry is None:
        return {
            "job_id": job_id,
            "phase": "ABORTED",
            "archive": None,
        }
    _get_tap().abort_job(entry.job_url)
    job_store.evict(job_id)
    return {
        "job_id": job_id,
        "phase": "ABORTED",
        "archive": archive_label(entry.endpoint),
    }


vo_tap_abort.__doc__ = (vo_tap_abort.__doc__ or "") + _ERROR_DOCSTRING
