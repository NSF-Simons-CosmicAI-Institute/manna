import io
from datetime import UTC, datetime

import pyarrow.parquet as pq
import pytest
from astropy.table import Table

from astro_archives_mcp import result_store
from astro_archives_mcp.config import get_settings
from astro_archives_mcp.shaper import (
    TRUNCATION_REASON_OVERSIZE,
    shape_inline_table,
    shape_table,
)

# Effective inline row cap shape_table actually enforces (schema default unless
# STABLE_INLINE_ROW_LIMIT is set). Boundary tests key off this.
INLINE_ROW_LIMIT = get_settings().inline_row_limit


@pytest.fixture(autouse=True)
def clear_store():
    result_store._STORE.clear()
    yield
    result_store._STORE.clear()


def _table(n_rows: int) -> Table:
    """A simple n-row table for size testing."""
    return Table({"ra": list(range(n_rows)), "dec": list(range(n_rows))})


def test_small_table_inline_tier_unchanged():
    t = _table(50)
    out = shape_table(t, archive="datalab", maxrec=10_000)
    assert out["row_count"] == 50
    assert out["truncated"] is False
    assert out["resource_uri"] is None
    assert out["rows"] is not None
    assert len(out["rows"]) == 50


def test_medium_table_promoted_to_resource_tier():
    t = _table(5_000)
    out = shape_table(t, archive="datalab", maxrec=10_000)
    assert out["row_count"] == 5_000
    assert out["truncated"] is False
    assert out["resource_uri"] is not None
    assert out["resource_uri"].startswith("resource://results/")
    assert out["resource_uri"].endswith(".parquet")
    assert out["preview"] is not None
    assert len(out["preview"]) == 50


def test_resource_tier_envelope_has_iso8601_expiry():
    t = _table(5_000)
    out = shape_table(t, archive="datalab", maxrec=10_000)
    exp = out["resource_expires_at"]
    assert exp is not None
    parsed = datetime.fromisoformat(exp)
    assert parsed.tzinfo is not None
    assert parsed > datetime.now(UTC)


def test_large_table_truncated_at_resource_limit():
    t = _table(200_000)
    out = shape_table(t, archive="datalab", maxrec=200_000)
    assert out["row_count"] == 200_000
    assert out["truncated"] is True
    assert out["truncation_reason"] == TRUNCATION_REASON_OVERSIZE
    assert out["resource_uri"] is not None
    assert len(out["hints"]) >= 1
    assert any("resource uri" in h["text"].lower() for h in out["hints"])


def test_edge_inline_limit_exact():
    t = _table(INLINE_ROW_LIMIT)
    out = shape_table(t, archive="datalab", maxrec=10_000)
    assert out["resource_uri"] is None
    assert out["row_count"] == INLINE_ROW_LIMIT


def test_edge_inline_limit_plus_one():
    t = _table(INLINE_ROW_LIMIT + 1)
    out = shape_table(t, archive="datalab", maxrec=10_000)
    assert out["resource_uri"] is not None


def test_wide_table_under_row_limit_spills_on_byte_limit():
    # Rows well under INLINE_ROW_LIMIT, but a fat string column pushes the
    # JSON payload over INLINE_BYTE_LIMIT — must spill to the Resource tier
    # rather than inlining. Guards small-context backends (e.g. a 64K vLLM)
    # against a single oversized inline result overflowing the model window.
    n_rows = INLINE_ROW_LIMIT - 1
    wide = "x" * 512
    t = Table({"blob": [wide] * n_rows})
    assert len(t) <= INLINE_ROW_LIMIT
    out = shape_table(t, archive="datalab", maxrec=10_000)
    assert out["resource_uri"] is not None
    assert out["rows"] is None
    assert out["preview"] is not None


def test_resource_tier_parquet_roundtrips():
    t = _table(5_000)
    out = shape_table(t, archive="datalab", maxrec=10_000)
    uuid = out["resource_uri"].rsplit("/", 1)[-1].removesuffix(".parquet")
    entry = result_store.get(uuid)
    assert entry is not None
    payload, mime = entry
    assert mime == "application/vnd.apache.parquet"
    reader = pq.read_table(io.BytesIO(payload))
    assert reader.num_rows == 5_000
    assert set(reader.column_names) == {"ra", "dec"}


def test_shape_inline_table_still_works_for_small_inputs():
    # The existing public function must remain unchanged
    t = _table(50)
    out = shape_inline_table(t, archive="datalab", maxrec=10_000)
    assert out["row_count"] == 50
    assert out["truncated"] is False
