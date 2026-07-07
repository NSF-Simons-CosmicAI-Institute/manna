import io
import json
import math
from datetime import datetime
from typing import Any, cast

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from astropy.table import Column, Table

from astro_archives_mcp import result_store
from astro_archives_mcp.config import get_settings

# The inline caps (rows / bytes) are read from get_settings() in shape_table,
# env-overridable via STABLE_INLINE_ROW_LIMIT / STABLE_INLINE_BYTE_LIMIT.
RESOURCE_ROW_LIMIT = 100_000
TRUNCATION_REASON_MAXREC = "maxrec_exceeded"
TRUNCATION_REASON_OVERSIZE = "oversize_for_resource_tier"


def shape_inline_table(
    table: Table,
    *,
    archive: str,
    maxrec: int,
) -> dict[str, Any]:
    """Convert an astropy.Table into the inline-tier response envelope.

    Inline tier only. The Resource tier is handled by _shape_resource
    once result sizes warrant it.
    """
    n_in = len(table)
    truncated = n_in > maxrec
    if truncated:
        # astropy stubs type Table slicing as TableColumns | Row | Table.
        table = cast(Table, table[:maxrec])

    columns: list[dict[str, Any]] = []
    for name in table.colnames:
        # String indexing returns a Column; astropy stubs widen it to a union.
        col = cast(Column, table[name])
        columns.append(
            {
                "name": name,
                "type": str(col.dtype),
                "unit": (str(col.unit) if col.unit and str(col.unit) else None),
                "ucd": _column_ucd(col),
                "description": col.description or None,
            }
        )

    rows: list[list[Any]] = []
    for row in table:
        rows.append([_normalize(row[name]) for name in table.colnames])

    return {
        "row_count": len(rows),
        "columns": columns,
        "rows": rows,
        "preview": None,
        "resource_uri": None,
        "truncated": truncated,
        "truncation_reason": "maxrec_exceeded" if truncated else None,
        "archive": archive,
        "next_steps": None,
        "hints": [],
    }


def shape_table(table: Table, *, archive: str, maxrec: int) -> dict[str, Any]:
    """Pick inline or Resource tier based on size; build the envelope.

    Public entry point for tabular tools. Delegates to:
    - shape_inline_table for small results (unchanged behavior)
    - _shape_resource for results above the inline threshold
    """
    settings = get_settings()
    n_rows = len(table)
    if n_rows <= settings.inline_row_limit:
        envelope = shape_inline_table(table, archive=archive, maxrec=maxrec)
        if _estimate_payload_bytes(envelope) <= settings.inline_byte_limit:
            return envelope
    return _shape_resource(table, archive=archive, maxrec=maxrec)


def _estimate_payload_bytes(envelope: dict) -> int:
    """Cheap upper bound on JSON-serialized size of the envelope."""
    return len(json.dumps(envelope, default=str))


def _shape_resource(table: Table, *, archive: str, maxrec: int) -> dict[str, Any]:
    """Build the Resource-tier envelope: preview + Parquet via MCP Resource URI."""
    true_count = len(table)
    visible = cast(Table, table[:RESOURCE_ROW_LIMIT])
    truncated = true_count > RESOURCE_ROW_LIMIT

    # astropy.Table -> pyarrow.Table -> Parquet bytes (no pandas dep)
    pa_table = pa.table({name: cast(Column, visible[name]).data for name in visible.colnames})
    buf = io.BytesIO()
    pq.write_table(pa_table, buf)
    uuid_hex, expires_at = result_store.put(buf.getvalue(), "application/vnd.apache.parquet")

    # Reuse inline envelope shape for preview rows
    preview_envelope = shape_inline_table(
        cast(Table, visible[:50]),
        archive=archive,
        maxrec=maxrec,
    )

    hints: list[dict[str, Any]] = []
    if truncated:
        hints.append(
            {
                "kind": "tip",
                "text": (
                    f"{RESOURCE_ROW_LIMIT} of {true_count} rows available at the "
                    "resource URI. For full results, narrow the query or raise maxrec."
                ),
                "source": None,
            }
        )

    return {
        "row_count": true_count,
        "columns": preview_envelope["columns"],
        "rows": None,
        "preview": preview_envelope["rows"],
        "resource_uri": f"resource://results/{uuid_hex}.parquet",
        "resource_expires_at": expires_at.isoformat(),
        "truncated": truncated,
        "truncation_reason": TRUNCATION_REASON_OVERSIZE if truncated else None,
        "archive": archive,
        "next_steps": None,
        "hints": hints,
    }


def _normalize(value: Any) -> Any:
    """Convert astropy / numpy scalars into JSON-friendly values; NaN/masked -> None.

    Vector-valued cells (e.g. SIA1 array columns like im_scale / im_naxis)
    become lists, with masked / NaN elements normalized to None.
    """
    if value is np.ma.masked:
        return None
    # Vector-valued cell: normalize element-wise. This must precede the
    # scalar-mask check below — bool() on a multi-element mask is ambiguous
    # and raises. MaskedArray.tolist() already maps masked entries to None.
    if np.ndim(value) > 0:
        return [_normalize(v) for v in value.tolist()]
    if hasattr(value, "mask") and bool(getattr(value, "mask", False)):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _column_ucd(col) -> str | None:
    """Resolve a column's UCD, checking the attribute first then meta variants.

    pyvo TAP results expose UCD via col.ucd. Hand-built astropy.Tables and some
    VOTable-loaded tables put it under col.meta['ucd'] or col.meta['UCD'].
    """
    direct = getattr(col, "ucd", None)
    if direct:
        return str(direct)
    meta = getattr(col, "meta", {}) or {}
    return meta.get("ucd") or meta.get("UCD")


def shape_registry_search_result(services: list[dict], *, maxrec: int) -> dict:
    """Envelope for vo_registry_search results."""
    truncated = len(services) > maxrec
    visible = services[:maxrec] if truncated else services
    return {
        "services": visible,
        "row_count": len(visible),
        "truncated": truncated,
        "truncation_reason": "maxrec_exceeded" if truncated else None,
    }


def shape_registry_describe_result(described: dict) -> dict:
    """Pass-through envelope for vo_registry_describe."""
    return dict(described)


def shape_blob_fetch(
    payload: bytes,
    *,
    source_url: str,
    mime_type: str,
    archive: str,
) -> dict:
    """Build the envelope for vo_sia_fetch and similar blob-returning tools.

    Stashes payload in result_store and returns a small JSON envelope
    pointing at the Resource URI. The bytes themselves do NOT flow
    inline.
    """
    uuid_hex, expires_at = result_store.put(payload, mime_type)
    # Cosmetic file extension based on MIME — helps clients suggest filenames
    ext_map = {
        "image/fits": "fits",
        "image/jpeg": "jpg",
        "image/png": "png",
        "application/vnd.apache.parquet": "parquet",
    }
    ext = ext_map.get(mime_type, "bin")
    return {
        "resource_uri": f"resource://results/{uuid_hex}.{ext}",
        "resource_expires_at": expires_at.isoformat(),
        "mime_type": mime_type,
        "source_url": source_url,
        "bytes_fetched": len(payload),
        "archive": archive,
        "next_steps": None,
        "hints": [],
    }


def shape_promotion(
    *,
    job_id: str,
    archive: str,
    phase: str,
    submitted_at: datetime,
) -> dict[str, Any]:
    """Envelope returned when vo_tap_query goes async (explicit mode=async
    or auto-mode timeout fallback).

    Shape-disjoint from the inline/Resource tabular envelopes: there are
    no rows yet. The LLM branches on the literal `mode: "async"`.
    """
    return {
        "mode": "async",
        "job_id": job_id,
        "phase": phase,
        "submitted_at": submitted_at.isoformat(),
        "archive": archive,
        "next_steps": [
            "Poll vo_tap_status(job_id) until phase is COMPLETED or ERROR",
            "Then call vo_tap_results(job_id) to fetch the data",
        ],
    }
