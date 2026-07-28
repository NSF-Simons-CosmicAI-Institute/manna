from astropy.table import Table

from manna.config import get_settings
from manna.shaper import (
    TRUNCATION_REASON_INLINE_CAP,
    TRUNCATION_REASON_MAXREC,
    is_oversize,
    shape_inline_table,
    shape_result_url,
    shape_table,
)

# Effective inline row cap shape_table enforces (schema default unless
# MANNA_INLINE_ROW_LIMIT is set). Boundary tests key off this.
INLINE_ROW_LIMIT = get_settings().inline_row_limit


def _table(n_rows: int) -> Table:
    """A simple n-row table for size testing."""
    return Table({"ra": list(range(n_rows)), "dec": list(range(n_rows))})


def test_small_table_inlines_fully():
    t = _table(50)
    out = shape_table(t, archive="datalab", maxrec=10_000)
    assert out["row_count"] == 50
    assert out["truncated"] is False
    assert out["truncation_reason"] is None
    assert out["rows"] is not None
    assert len(out["rows"]) == 50
    # The stateless envelope has no resource fields.
    assert "resource_uri" not in out
    assert "preview" not in out


def test_over_inline_row_limit_truncates_inline():
    t = _table(INLINE_ROW_LIMIT + 500)
    out = shape_table(t, archive="datalab", maxrec=10_000)
    assert out["truncated"] is True
    assert out["truncation_reason"] == TRUNCATION_REASON_INLINE_CAP
    # Only the inline cap's worth of rows are actually returned.
    assert out["row_count"] == INLINE_ROW_LIMIT
    assert len(out["rows"]) == INLINE_ROW_LIMIT
    assert len(out["hints"]) >= 1
    assert f"of {INLINE_ROW_LIMIT + 500} rows" in out["hints"][0]["text"]


def test_edge_inline_limit_exact_not_truncated():
    t = _table(INLINE_ROW_LIMIT)
    out = shape_table(t, archive="datalab", maxrec=10_000)
    assert out["truncated"] is False
    assert out["row_count"] == INLINE_ROW_LIMIT


def test_edge_inline_limit_plus_one_truncates():
    t = _table(INLINE_ROW_LIMIT + 1)
    out = shape_table(t, archive="datalab", maxrec=10_000)
    assert out["truncated"] is True
    assert out["row_count"] == INLINE_ROW_LIMIT


def test_maxrec_is_binding_cap_reported_as_maxrec():
    # maxrec below the inline cap clips first — reason should be maxrec, not
    # the inline cap.
    maxrec = INLINE_ROW_LIMIT // 2
    t = _table(INLINE_ROW_LIMIT)
    out = shape_table(t, archive="datalab", maxrec=maxrec)
    assert out["truncated"] is True
    assert out["truncation_reason"] == TRUNCATION_REASON_MAXREC
    assert out["row_count"] == maxrec


def test_wide_table_under_row_limit_truncated_on_byte_cap():
    # Rows well under INLINE_ROW_LIMIT, but a fat string column pushes the
    # JSON payload over the byte cap. shape_table must actually shed rows
    # (not just flag truncation) so the inline payload fits the cap.
    n_rows = INLINE_ROW_LIMIT - 1
    wide = "x" * 512
    t = Table({"blob": [wide] * n_rows})
    out = shape_table(t, archive="datalab", maxrec=10_000)
    assert out["truncated"] is True
    assert out["truncation_reason"] == TRUNCATION_REASON_INLINE_CAP
    assert out["row_count"] < n_rows
    byte_limit = get_settings().inline_byte_limit
    import json

    assert len(json.dumps(out, default=str)) <= byte_limit


def test_shape_inline_table_unchanged_for_small_inputs():
    t = _table(50)
    out = shape_inline_table(t, archive="datalab", maxrec=10_000)
    assert out["row_count"] == 50
    assert out["truncated"] is False


def test_is_oversize_false_for_small_table():
    assert is_oversize(_table(50)) is False


def test_is_oversize_true_over_row_cap():
    assert is_oversize(_table(INLINE_ROW_LIMIT + 1)) is True


def test_is_oversize_true_on_byte_cap_under_row_cap():
    wide = "x" * 1024
    t = Table({"blob": [wide] * (INLINE_ROW_LIMIT - 1)})
    assert is_oversize(t) is True


def test_shape_result_url_carries_urls_and_recipe():
    job_url = "https://datalab.noirlab.edu/tap/async/42"
    result_url = job_url + "/results/result"
    out = shape_result_url(job_url=job_url, result_url=result_url, archive="datalab")
    assert out["phase"] == "COMPLETED"
    assert out["job_url"] == job_url
    assert out["result_url"] == result_url
    assert out["format"] == "votable"
    assert out["fetch_recipe"]["module"] == "pyvo"
    assert job_url in out["fetch_recipe"]["code"]
    assert result_url in out["fetch_recipe"]["alternative"]
    assert "rows" not in out


def test_shape_result_url_tolerates_missing_result_url():
    job_url = "https://x/async/1"
    out = shape_result_url(job_url=job_url, result_url=None, archive="x")
    assert out["result_url"] is None
    # The pyvo recipe still works from job_url alone; no astropy alternative.
    assert "alternative" not in out["fetch_recipe"]
    assert job_url in out["fetch_recipe"]["code"]


def test_shape_result_url_next_steps_command_recipe_execution():
    # Small models treat descriptive next_steps as someone else's job and
    # abandon completed results (observed with Qwen in the jhub persona).
    # The steps must be imperative, name the model's own code-execution
    # tool, and forbid re-running the query.
    out = shape_result_url(
        job_url="https://x/async/1",
        result_url="https://x/async/1/results/result",
        archive="x",
    )
    joined = " ".join(out["next_steps"])
    assert "fetch_recipe.code" in joined
    assert "code-execution tool" in joined
    assert "do NOT re-run" in joined
    # Fallback when pyvo is missing from the client's kernel.
    assert "fetch_recipe.alternative" in joined
    # Last resort for clients that cannot execute code at all.
    assert "SELECT TOP" in joined
    assert "vo_tap_query" in joined


def test_shape_result_url_omits_alternative_step_without_result_url():
    out = shape_result_url(job_url="https://x/async/1", result_url=None, archive="x")
    joined = " ".join(out["next_steps"])
    # No result_url ⇒ no fetch_recipe.alternative ⇒ the step must not point
    # at a field that does not exist.
    assert "fetch_recipe.alternative" not in joined
    assert "fetch_recipe.code" in joined
