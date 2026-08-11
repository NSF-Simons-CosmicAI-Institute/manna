"""Tools for IVOA TAP."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import Field

from manna._archive_label import archive_label
from manna._fingerprint import query_fingerprint
from manna._url_guard import ensure_safe_url
from manna.archives._endpoints import (
    tap_endpoint_description,
    tap_endpoint_urls,
)
from manna.archives._traps import loud_trap_guidance
from manna.backends.tap import TapClient
from manna.config import get_settings
from manna.errors import (
    ArchiveError,
    DalQueryError,
    JobNotReadyError,
    TimeoutArchiveError,
    ValidationError,
    wrap_tool_errors,
)
from manna.shaper import (
    attach_cache_fields,
    is_oversize,
    shape_inline_table,
    shape_promotion,
    shape_result_url,
)
from manna.tools._constants import _ERROR_DOCSTRING

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

    Raises ArchiveError if the async submission itself fails (so the caller
    still gets a structured payload via wrap_tool_errors).

    Nothing is recorded server-side: the returned job_url is the whole handle.
    """
    job_url = _get_tap().submit_async(endpoint=endpoint, adql=adql, maxrec=maxrec)
    return shape_promotion(
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
                "job_url. 'auto' (default) = try sync first; on timeout, "
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

    2. Promotion envelope (mode='async', job_url, fetch_recipe).
       Returned when mode='async', when mode='auto' and the sync attempt
       timed out, or when mode='auto' and the sync result was too large
       to inline. Disambiguate by checking payload.get('mode') == 'async'.

    mode='sync' with an oversize result does NOT auto-promote — it raises
    validation_error telling you to re-run with mode='async'.

    For async results, poll vo_tap_status(job_url) until phase is
    COMPLETED, then call vo_tap_results(job_url) — or fetch client-side
    with the pyvo fetch_recipe carried on the promotion envelope. Pass the
    job_url back verbatim; it is the job's only handle.

    Successful result envelopes also carry `query_fingerprint` and a
    `save_recipe` — after loading the result, execute save_recipe.code
    client-side to persist a CSV + manna_cache/catalog.csv row so the
    query need not be re-run later.
    """
    ensure_safe_url(endpoint, param="endpoint")
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
            return attach_cache_fields(
                shape_inline_table(table, archive=archive_label(endpoint), maxrec=maxrec),
                fingerprint=query_fingerprint("tap", endpoint, adql),
                tool="tap",
                endpoint=endpoint,
                query=adql,
                maxrec=maxrec,
            )

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
        return attach_cache_fields(
            shape_inline_table(table, archive=archive_label(endpoint), maxrec=maxrec),
            fingerprint=query_fingerprint("tap", endpoint, adql),
            tool="tap",
            endpoint=endpoint,
            query=adql,
            maxrec=maxrec,
        )


vo_tap_query.__doc__ = (vo_tap_query.__doc__ or "") + _ERROR_DOCSTRING


_JOB_URL_FIELD = Field(
    description=(
        "The upstream job_url returned by vo_tap_query when it went async "
        "(mode='async' or auto-promote). Pass it back verbatim — it is the "
        "job's only handle."
    ),
    examples=["https://almascience.eso.org/tap/async/1234567"],
)


def _endpoint_from_job_url(job_url: str) -> str:
    """Recover the TAP base endpoint from a UWS job URL.

    Standard UWS layout is <endpoint>/async/<id>; splitting keeps the
    vo_tap_results fingerprint identical to the one vo_tap_query computed
    at submission, so a promoted query dedupes against its inline twin.
    Non-standard URLs fall back to the job_url itself — still stable.
    """
    return job_url.split("/async/")[0] if "/async/" in job_url else job_url


def _status_payload(*, job, job_url: str) -> dict:
    """Build the status response from a live AsyncTAPJob."""
    error_message = None
    if job.phase == "ERROR":
        es = getattr(job, "error_summary", None)
        if es is not None:
            error_message = getattr(es, "message", None) or str(es)

    started = getattr(job, "starttime", None)
    ended = getattr(job, "endtime", None)
    return {
        "job_url": job_url,
        "phase": job.phase,
        "started_at": started.isoformat() if started else None,
        "ended_at": ended.isoformat() if ended else None,
        "error_message": error_message,
        "archive": archive_label(job_url),
    }


@wrap_tool_errors
def vo_tap_status(job_url: Annotated[str, _JOB_URL_FIELD]) -> dict:
    """Fetch the live UWS phase for an async TAP job.

    Returns {job_url, phase, started_at, ended_at, error_message, archive}.
    Phase is read live from the upstream service; no local caching.

    Phases per UWS spec: PENDING, QUEUED, EXECUTING, COMPLETED, ERROR,
    ABORTED, ARCHIVED, HELD, SUSPENDED, UNKNOWN. The LLM branches on
    the string.

    If the archive has deleted or expired the job, this raises job_gone
    (retry_strategy=abandon) — re-submit rather than continuing to poll.
    """
    ensure_safe_url(job_url, param="job_url")
    job = _get_tap().load_job(job_url)
    return _status_payload(job=job, job_url=job_url)


vo_tap_status.__doc__ = (vo_tap_status.__doc__ or "") + _ERROR_DOCSTRING


@wrap_tool_errors
def vo_tap_results(job_url: Annotated[str, _JOB_URL_FIELD]) -> dict:
    """Return access info for a COMPLETED async TAP job.

    The server does NOT fetch the result bytes. It returns the upstream
    job_url, the direct result_url, and a pyvo fetch_recipe so the client
    loads the data itself (e.g. in a Jupyter kernel). Anonymous access
    only.

    After calling this, execute the returned fetch_recipe code with your
    code-execution tool to load the data. The query already ran — do not
    re-submit it.

    If the job is not yet COMPLETED, raises job_not_ready (retry_strategy=poll).
    If the job ended in ERROR, raises tap_query_error with the upstream
    message. If the archive no longer has the job, raises job_gone
    (retry_strategy=abandon).
    """
    ensure_safe_url(job_url, param="job_url")
    job = _get_tap().load_job(job_url)
    phase = job.phase

    if phase == "ERROR":
        es = getattr(job, "error_summary", None)
        msg = getattr(es, "message", None) if es is not None else None
        raise DalQueryError(message=msg or "Async TAP job ended in ERROR.")
    if phase == "ABORTED":
        raise ValidationError(
            message="This job was aborted; re-submit if you still want results.",
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
    # Fingerprint continuity: prefer the job's own ADQL (pyvo exposes it on
    # AsyncTAPJob); a job that doesn't expose it falls back to the job_url,
    # stable for the life of the job — exactly the re-fetch window.
    try:
        job_adql = getattr(job, "query", None)
    except Exception:  # noqa: BLE001 — pyvo attribute access is best-effort
        job_adql = None
    identity = job_adql or job_url
    endpoint = _endpoint_from_job_url(job_url)
    return attach_cache_fields(
        shape_result_url(
            job_url=job_url,
            result_url=result_url,
            archive=archive_label(job_url),
        ),
        fingerprint=query_fingerprint("tap", endpoint, identity),
        tool="tap",
        endpoint=endpoint,
        query=identity,
    )


vo_tap_results.__doc__ = (vo_tap_results.__doc__ or "") + _ERROR_DOCSTRING


@wrap_tool_errors
def vo_tap_abort(job_url: Annotated[str, _JOB_URL_FIELD]) -> dict:
    """Cancel a running async TAP job.

    Sends UWS DELETE upstream. Idempotent: aborting an already-deleted or
    expired job returns the same {job_url, phase=ABORTED} shape rather than
    raising (abort_job swallows the 4xx).
    """
    ensure_safe_url(job_url, param="job_url")
    _get_tap().abort_job(job_url)
    return {
        "job_url": job_url,
        "phase": "ABORTED",
        "archive": archive_label(job_url),
    }


vo_tap_abort.__doc__ = (vo_tap_abort.__doc__ or "") + _ERROR_DOCSTRING
