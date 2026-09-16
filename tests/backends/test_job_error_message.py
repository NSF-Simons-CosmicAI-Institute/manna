"""job_error_message reads the UWS errorSummary the way pyvo actually stores it.

Regression for a bug that hid every archive's async error diagnostics: the tools
read `job.error_summary`, an attribute pyvo's AsyncTAPJob has never had (it only
exposes the parsed UWS tree as `job._job`, and the message text sits behind
`errorsummary.message.content`). `getattr(..., None)` swallowed the miss, so the
model always saw the generic "Async TAP job ended in ERROR." — and NRAO's
perfectly good `IllegalArgumentException:Function [LOWER] is not found in
TapSchema` was written up as an archive defect (findings N-06, since retracted).

These tests parse real UWS XML with pyvo's own parser so the accessor is checked
against pyvo's structure, not a hand-rolled fake.
"""

from io import BytesIO

from pyvo.dal import AsyncTAPJob
from pyvo.io.uws import parse_job

from manna.backends.tap import job_error_message

_UWS_NS = 'xmlns:uws="http://www.ivoa.net/xml/UWS/v1.0" xmlns:xlink="http://www.w3.org/1999/xlink"'


def _job_from_xml(body: str) -> AsyncTAPJob:
    """A real AsyncTAPJob carrying a JobSummary parsed by pyvo, no HTTP."""
    xml = f"<uws:job {_UWS_NS}><uws:jobId>j1</uws:jobId>{body}</uws:job>".encode()
    job = AsyncTAPJob.__new__(AsyncTAPJob)
    job._job = parse_job(BytesIO(xml))
    return job


def test_returns_the_upstream_message_text():
    # Verbatim shape of an NRAO ERROR job, 2026-09-10.
    job = _job_from_xml(
        "<uws:phase>ERROR</uws:phase>"
        '<uws:errorSummary type="fatal" hasDetail="false">'
        "<uws:message>IllegalArgumentException:Function [LOWER] is not found in TapSchema"
        "</uws:message></uws:errorSummary>"
    )
    assert job_error_message(job) == (
        "IllegalArgumentException:Function [LOWER] is not found in TapSchema"
    )


def test_returns_none_when_the_job_carries_no_error_summary():
    job = _job_from_xml("<uws:phase>ERROR</uws:phase>")
    assert job_error_message(job) is None


def test_returns_none_for_an_empty_message_element():
    job = _job_from_xml(
        "<uws:phase>ERROR</uws:phase>"
        '<uws:errorSummary type="fatal" hasDetail="false"><uws:message/></uws:errorSummary>'
    )
    assert job_error_message(job) is None


def test_pyvo_job_has_no_public_error_summary_attribute():
    """The attribute the old code read. If pyvo ever adds it, revisit the
    accessor; until then this pins why job_error_message goes through _job."""
    job = _job_from_xml("<uws:phase>ERROR</uws:phase>")
    assert not hasattr(job, "error_summary")
