from manna.errors import JobNotReadyError, error_to_payload


def test_job_not_ready_payload_has_canonical_shape():
    err = JobNotReadyError(
        message="Job is still EXECUTING.",
        hint="Poll vo_tap_status until phase is COMPLETED.",
    )
    payload = error_to_payload(err, request_id="abc12")
    assert payload["error_class"] == "job_not_ready"
    assert payload["retry_strategy"] == "poll"
    assert payload["message"] == "Job is still EXECUTING."
    assert payload["hint"] == "Poll vo_tap_status until phase is COMPLETED."
    assert payload["request_id"] == "abc12"


def test_job_not_ready_propagates_message():
    err = JobNotReadyError(message="Phase is QUEUED.")
    payload = error_to_payload(err)
    assert payload["error_class"] == "job_not_ready"
    assert payload["retry_strategy"] == "poll"
    assert payload["message"] == "Phase is QUEUED."
