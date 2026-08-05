"""IVOA TAP backend: sync + async wrappers over pyvo.

This module is the ONLY place that imports pyvo. Tools work in terms of
job_url strings and astropy.Table — they do not touch AsyncTAPJob.
"""

import logging

import pyvo
import requests
from astropy.table import Table
from pyvo.dal import AsyncTAPJob
from pyvo.dal.exceptions import DALFormatError, DALQueryError, DALServiceError

from manna.errors import ArchiveError, DalQueryError, JobGoneError, TimeoutArchiveError

log = logging.getLogger(__name__)


_JOB_GONE_STATUSES = frozenset({404, 410})


def _http_status(e: Exception) -> int | None:
    """HTTP status carried by a pyvo exception, if any.

    Mirrors _is_timeout's traversal: pyvo attaches the original exception to
    `.cause`, and we also walk the standard chain for versions that use
    `raise ... from`.
    """
    for candidate in (getattr(e, "cause", None), e.__cause__, e.__context__):
        status = getattr(getattr(candidate, "response", None), "status_code", None)
        if status is not None:
            return status
    return None


def _is_timeout(e: DALFormatError) -> bool:
    """True if a DALFormatError wraps a requests read/connect timeout.

    pyvo carries the original exception on `.cause`; we also check the
    standard `__cause__`/`__context__` chain as a fallback for pyvo
    versions that raise via `raise ... from`.
    """
    for candidate in (getattr(e, "cause", None), e.__cause__, e.__context__):
        if isinstance(candidate, requests.exceptions.Timeout):
            return True
    return False


class TapClient:
    """Wrapper around pyvo.dal.TAPService + AsyncTAPJob.

    All pyvo exceptions are mapped to project ToolExecutionError
    subclasses at the boundary; tools never see DAL errors directly.
    """

    def __init__(self, *, sync_timeout_seconds: float = 20.0) -> None:
        # Default timeout applied to every HTTP call pyvo makes through
        # the session wrapper. Used for sync queries (the soft deadline
        # the auto-promote path discriminates on) and async submit.
        # AsyncTAPJob.wait(timeout=...) overrides this for polling.
        self._sync_timeout = sync_timeout_seconds

    def _session(self) -> requests.Session:
        # pyvo accepts a requests.Session via TAPService(session=...).
        # Note: pyvo passes the session's `timeout` per-call, so we
        # set it via Session.request below.
        session = requests.Session()

        # Wrap request to enforce a default timeout when the caller
        # doesn't pass one (pyvo's internal calls do not). This is the
        # cleanest seam — pyvo's TAPService delegates HTTP to this
        # session and inherits the timeout.
        original = session.request

        def request_with_timeout(method, url, **kwargs):
            kwargs.setdefault("timeout", self._sync_timeout)
            return original(method, url, **kwargs)

        session.request = request_with_timeout  # type: ignore[assignment]
        return session

    def query(self, *, endpoint: str, adql: str, maxrec: int = 10_000) -> Table:
        """Synchronous TAP query. Bounded by sync_timeout_seconds (default 20s).

        Raises:
            DalQueryError on bad ADQL.
            ArchiveError on service errors / timeouts / unreachable hosts.
        """
        try:
            service = pyvo.dal.TAPService(endpoint, session=self._session())
            result = service.search(adql, maxrec=maxrec)  # pyright: ignore[reportCallIssue]
        except DALQueryError as e:
            raise DalQueryError(message=str(e)) from e
        except DALServiceError as e:
            raise ArchiveError(message=str(e)) from e
        except DALFormatError as e:
            # pyvo wraps a read timeout during response fetch/parse here.
            # DALFormatError is a sibling of DALServiceError under
            # DALProtocolError, so it reaches this clause unshadowed.
            if _is_timeout(e):
                raise TimeoutArchiveError(message=f"TAP sync request timed out: {e}") from e
            raise ArchiveError(message=str(e)) from e
        except requests.exceptions.Timeout as e:
            raise TimeoutArchiveError(message=f"TAP sync request timed out: {e}") from e
        return result.to_table()

    def submit_async(
        self,
        *,
        endpoint: str,
        adql: str,
        maxrec: int = 10_000,
    ) -> str:
        """Submit a TAP query as an async UWS job and start execution.

        Returns the absolute job_url. The caller (the LLM client holding
        the returned job_url) is the job's lifetime owner; this method
        records no server-side state.

        IMPORTANT: pyvo's AsyncTAPJob defaults to delete=True, which
        registers an atexit-style cleanup that DELETEs the upstream job
        when the Python object is garbage-collected. We MUST disable
        that. Setting `_delete_on_exit = False` before the local
        reference falls out of scope prevents the upstream job from
        being silently destroyed between tool calls.
        """
        try:
            service = pyvo.dal.TAPService(endpoint, session=self._session())
            job = service.submit_job(adql, maxrec=maxrec)
            job._delete_on_exit = False  # noqa: SLF001 — see docstring
            job.run()  # transitions PENDING → QUEUED/EXECUTING
        except DALQueryError as e:
            raise DalQueryError(message=str(e)) from e
        except DALServiceError as e:
            raise ArchiveError(message=str(e)) from e
        except DALFormatError as e:
            # A read timeout during submit is still just an archive error
            # here — submit_async has no auto-promote path to feed.
            if _is_timeout(e):
                raise ArchiveError(message=f"TAP async submit timed out: {e}") from e
            raise ArchiveError(message=str(e)) from e
        except requests.exceptions.Timeout as e:
            raise ArchiveError(message=f"TAP async submit timed out: {e}") from e
        return job.url  # pyright: ignore[reportReturnType]

    def load_job(self, job_url: str) -> AsyncTAPJob:
        """Re-hydrate an AsyncTAPJob from a previously-stored job_url.

        `delete=False` is critical — without it, the AsyncTAPJob's
        __del__ would DELETE the upstream job as soon as the caller
        (a tool function) returned. See submit_async docstring.
        """
        try:
            return AsyncTAPJob(job_url, session=self._session(), delete=False)
        except DALServiceError as e:
            if _http_status(e) in _JOB_GONE_STATUSES:
                raise JobGoneError(
                    message=(
                        "The archive no longer has this job — it was deleted or "
                        "aged out of its job store. Re-submit the query with "
                        "vo_tap_query if you still need the result."
                    )
                ) from e
            raise ArchiveError(message=str(e)) from e

    def abort_job(self, job_url: str) -> None:
        """Send UWS DELETE for a job. Idempotent: 404 / connection-refused
        on a previously-deleted job is swallowed so callers can abort
        twice without branching.

        We construct the AsyncTAPJob directly here (instead of via
        load_job) so that DALServiceError from the construction-time
        GET — which happens on already-deleted jobs — is caught and
        swallowed at the same level as failures from job.delete().
        """
        try:
            job = AsyncTAPJob(job_url, session=self._session(), delete=False)
            job.delete()
        except DALServiceError as e:
            # pyvo raises DALServiceError on HTTP errors during delete
            # OR during the construction-time GET. 4xx on a job that
            # was already removed is fine; swallow it.
            log.debug("abort_job swallowed DALServiceError: %s", e)
        except requests.exceptions.RequestException as e:
            log.debug("abort_job swallowed RequestException: %s", e)
