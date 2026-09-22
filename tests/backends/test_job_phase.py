"""job_phase reads pyvo's cached UWS phase without issuing a fresh GET.

AsyncTAPJob.phase is a property that refetches on every access; the
constructor (or a prior load_job) has already fetched the job, so the phase
parsed into job._job is current for the read that just happened. Re-reading
job.phase after that costs an extra upstream GET per access — this backend
seam lets tools/tap.py read the cached value instead.

Mirrors tests/backends/test_job_error_message.py: builds a real AsyncTAPJob
from parsed UWS XML with no HTTP involved (the object carries no session, so
any code path that tried to fetch would raise).
"""

from io import BytesIO
from types import SimpleNamespace

from pyvo.dal import AsyncTAPJob
from pyvo.io.uws import parse_job

from manna.backends.tap import job_phase

_UWS_NS = 'xmlns:uws="http://www.ivoa.net/xml/UWS/v1.0" xmlns:xlink="http://www.w3.org/1999/xlink"'


def _job_from_xml(body: str) -> AsyncTAPJob:
    """A real AsyncTAPJob carrying a JobSummary parsed by pyvo, no HTTP."""
    xml = f"<uws:job {_UWS_NS}><uws:jobId>j1</uws:jobId>{body}</uws:job>".encode()
    job = AsyncTAPJob.__new__(AsyncTAPJob)
    job._job = parse_job(BytesIO(xml))
    return job


def test_reads_the_cached_phase_without_a_refetch():
    job = _job_from_xml("<uws:phase>EXECUTING</uws:phase>")
    # job carries no session at all — any HTTP attempt would raise, so a
    # passing assertion here is itself proof no fetch happened.
    assert job_phase(job) == "EXECUTING"


def test_falls_through_to_the_plain_phase_attribute_when_no_cached_tree():
    job = SimpleNamespace(phase="COMPLETED")
    assert job_phase(job) == "COMPLETED"
