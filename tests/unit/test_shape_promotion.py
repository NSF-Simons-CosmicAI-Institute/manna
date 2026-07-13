from datetime import UTC, datetime

from astro_archives_mcp.shaper import shape_promotion

_JOB_URL = "https://datalab.noirlab.edu/tap/async/42"


def test_shape_promotion_basic_envelope():
    submitted = datetime(2026, 6, 8, 14, 30, 0, tzinfo=UTC)
    env = shape_promotion(
        job_id="0abc123def45",
        job_url=_JOB_URL,
        archive="alma",
        phase="EXECUTING",
        submitted_at=submitted,
    )
    assert env["mode"] == "async"
    assert env["job_id"] == "0abc123def45"
    assert env["job_url"] == _JOB_URL
    assert env["phase"] == "EXECUTING"
    assert env["archive"] == "alma"
    assert env["submitted_at"] == "2026-06-08T14:30:00+00:00"


def test_shape_promotion_carries_pyvo_fetch_recipe():
    env = shape_promotion(
        job_id="0abc",
        job_url=_JOB_URL,
        archive="datalab",
        phase="QUEUED",
        submitted_at=datetime.now(UTC),
    )
    recipe = env["fetch_recipe"]
    assert recipe["module"] == "pyvo"
    # The recipe must embed the real upstream job URL so the client can
    # re-hydrate the job with pyvo.dal.AsyncTAPJob.
    assert _JOB_URL in recipe["code"]
    assert "AsyncTAPJob" in recipe["code"]
    assert "fetch_result" in recipe["code"]


def test_shape_promotion_next_steps_reference_lifecycle_and_fetch():
    env = shape_promotion(
        job_id="0abc",
        job_url=_JOB_URL,
        archive="datalab",
        phase="QUEUED",
        submitted_at=datetime.now(UTC),
    )
    joined = " ".join(env["next_steps"])
    assert "vo_tap_status" in joined
    assert "vo_tap_results" in joined or "fetch_recipe" in joined


def test_shape_promotion_omits_tabular_keys():
    # Disjoint shape: no rows / columns / resource fields.
    env = shape_promotion(
        job_id="0abc",
        job_url=_JOB_URL,
        archive="alma",
        phase="EXECUTING",
        submitted_at=datetime.now(UTC),
    )
    for key in ("rows", "columns", "preview", "resource_uri", "row_count"):
        assert key not in env, f"{key} must not appear in promotion envelope"
