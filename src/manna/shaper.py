import json
import math
from datetime import datetime
from typing import Any, cast

import numpy as np
from astropy.table import Column, Table

from manna.config import get_settings

# The inline caps (rows / bytes) are read from get_settings(), env-overridable
# via MANNA_INLINE_ROW_LIMIT / MANNA_INLINE_BYTE_LIMIT.
TRUNCATION_REASON_MAXREC = "maxrec_exceeded"
# #40 dropped the resource tier — oversize inline results now truncate/route to async, so the
# old TRUNCATION_REASON_OVERSIZE ("oversize_for_resource_tier") becomes INLINE_CAP here.
TRUNCATION_REASON_INLINE_CAP = "inline_cap_exceeded"
# #36's registry-describe catalog constants are orthogonal to the result-envelope change.
TRUNCATION_REASON_DESCRIBE_OVERSIZE = "describe_columns_omitted"

# In catalog (degraded) mode each table collapses to name + description +
# column_count. Descriptions are clipped so a many-table catalog stays compact;
# the table count itself is trimmed to fit the byte budget (see _fit_tables).
_DESCRIBE_CATALOG_DESC_MAXLEN = 280


def shape_inline_table(
    table: Table,
    *,
    archive: str,
    maxrec: int,
) -> dict[str, Any]:
    """Convert an astropy.Table into the inline response envelope.

    Rows flow inline. Callers that must NOT inline large results (TAP)
    check `is_oversize` first and route to the async/result-URL path;
    discovery tools (cone / SIA search) inline up to the cap and let
    `shape_table` truncate the tail.
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
        "truncated": truncated,
        "truncation_reason": TRUNCATION_REASON_MAXREC if truncated else None,
        "archive": archive,
        "next_steps": None,
        "hints": [],
    }


def shape_table(table: Table, *, archive: str, maxrec: int) -> dict[str, Any]:
    """Inline envelope for discovery tools (cone / SIA search).

    These are synchronous DAL queries with no async job or persistent
    archive URL to hand back, so a result larger than the inline cap is
    truncated inline with `truncated=true` and a hint to narrow the
    search. TAP does NOT use this path — it checks `is_oversize` and
    routes oversize results to the async / result-URL flow instead.
    """
    settings = get_settings()
    total = len(table)
    # Largest prefix that satisfies both the maxrec and inline row caps...
    limit = min(total, maxrec, settings.inline_row_limit)
    envelope = _inline_prefix(table, archive, limit)
    # ...then shrink further until it also fits the byte cap.
    while envelope["row_count"] > 1 and not _fits_inline_bytes(envelope):
        limit = max(1, int(envelope["row_count"] * 0.8))
        envelope = _inline_prefix(table, archive, limit)

    shown = envelope["row_count"]
    if shown < total:
        envelope["truncated"] = True
        # maxrec is the binding cap only when it alone clipped the result.
        maxrec_bound = total > maxrec and shown == maxrec
        envelope["truncation_reason"] = (
            TRUNCATION_REASON_MAXREC if maxrec_bound else TRUNCATION_REASON_INLINE_CAP
        )
        envelope["hints"] = [
            {
                "kind": "tip",
                "text": (
                    f"Showing {shown} of {total} rows (inline cap). Narrow the "
                    "search region or lower maxrec to see every row inline."
                ),
                "source": None,
            }
        ]
    return envelope


def _inline_prefix(table: Table, archive: str, n: int) -> dict[str, Any]:
    """Inline envelope for the first `n` rows, with no truncation flags set
    (the caller decides whether the prefix represents a truncation)."""
    prefix = cast(Table, table[:n])
    return shape_inline_table(prefix, archive=archive, maxrec=n)


def is_oversize(table: Table) -> bool:
    """True if `table` would exceed the inline row OR byte cap.

    TAP tools call this to decide between inlining a result and routing
    it to the async / result-URL flow. Cheap: the byte estimate only
    runs when the row count is already within the row cap.
    """
    settings = get_settings()
    if len(table) > settings.inline_row_limit:
        return True
    envelope = shape_inline_table(table, archive="", maxrec=len(table))
    return not _fits_inline_bytes(envelope)


def _fits_inline_bytes(envelope: dict) -> bool:
    return _estimate_payload_bytes(envelope) <= get_settings().inline_byte_limit


def _estimate_payload_bytes(envelope: dict) -> int:
    """Cheap upper bound on JSON-serialized size of the envelope."""
    return len(json.dumps(envelope, default=str))


def build_fetch_recipe(job_url: str, result_url: str | None = None) -> dict[str, Any]:
    """Client-side recipe for loading an async TAP result with pyvo.

    The server never fetches the result bytes; it hands the LLM the
    upstream job URL and the code to load it in the user's own Python
    environment (e.g. a Jupyter kernel). Anonymous access only.
    """
    code = (
        "import pyvo\n"
        f"job = pyvo.dal.AsyncTAPJob({job_url!r})\n"
        "job.raise_if_error()\n"
        "table = job.fetch_result().to_table()"
    )
    recipe: dict[str, Any] = {"module": "pyvo", "code": code}
    if result_url:
        recipe["alternative"] = (
            f"from astropy.table import Table\ntable = Table.read({result_url!r}, format='votable')"
        )
    return recipe


def shape_result_url(
    *,
    job_url: str,
    result_url: str | None,
    archive: str,
    phase: str = "COMPLETED",
) -> dict[str, Any]:
    """Envelope for a COMPLETED async TAP job.

    Carries the upstream job URL, the direct result URL, and a pyvo
    fetch recipe. No result bytes flow through the server — the client
    loads the data itself.

    next_steps is written for the weakest reader: imperative, names the
    model's own code-execution tool, and forbids re-running the query.
    Small models (observed: small local models behind the Jupyter AI persona) treat
    descriptive phrasing like "fetch client-side" as someone else's job
    and abandon the completed result.
    """
    next_steps = [
        "The query already ran and its full result is ready — do NOT re-run "
        "it. Execute the Python in fetch_recipe.code with your "
        "code-execution tool (e.g. run it in a notebook cell); it loads the "
        "result as an astropy Table named `table`.",
    ]
    if result_url:
        next_steps.append(
            "If `import pyvo` fails, execute fetch_recipe.alternative "
            "instead — it needs only astropy."
        )
    next_steps.append(
        "Only if you cannot execute code at all: re-run vo_tap_query with a "
        "narrower query (SELECT TOP N, tighter WHERE, or aggregates like "
        "COUNT/GROUP BY) so the result fits inline."
    )
    return {
        "phase": phase,
        "job_url": job_url,
        "result_url": result_url,
        "format": "votable",
        "archive": archive,
        "next_steps": next_steps,
        "fetch_recipe": build_fetch_recipe(job_url, result_url),
        "hints": [
            {
                "kind": "tip",
                "text": "result_url is valid until the archive expires the async job.",
                "source": None,
            },
            {
                "kind": "tip",
                "text": "Anonymous archives only — authenticated archives are "
                "not yet supported for client-side fetch.",
                "source": None,
            },
        ],
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


def _describe_catalog_entry(table: dict) -> dict:
    """Collapse one table dict to a catalog entry: name + clipped description +
    column_count. Drops the per-column arrays that drive the size blowup."""
    desc = table.get("description")
    if isinstance(desc, str) and len(desc) > _DESCRIBE_CATALOG_DESC_MAXLEN:
        desc = desc[: _DESCRIBE_CATALOG_DESC_MAXLEN - 3].rstrip() + "..."
    return {
        "name": table.get("name"),
        "description": desc,
        "column_count": len(table.get("columns") or []),
    }


def _filter_describe_tables(tables: list[dict], table_filter: str) -> list[dict]:
    """Case-insensitive substring match over each table's *name*.

    Filtering happens here, in our server, on the already-fetched introspection —
    NOT delegated to the archive. Large services' own query endpoints are
    unreliable for this (e.g. Data Lab's sync TAP 504s on tap_schema, and it
    ignores VOSI detail=min), whereas the full VOSI /tables fetch is fast and
    dependable. So we always have the whole table list in hand and narrow it here.

    Match is on the table name only, not description: it keeps a precise filter
    (e.g. 'gaia_source') narrow enough that the matches' columns fit inline —
    matching descriptions pulls in every table that merely *mentions* the term
    (e.g. 100+ cross-match tables), and descriptions aren't populated on every
    service anyway.
    """
    needle = table_filter.strip().lower()
    if not needle:
        return tables
    return [t for t in tables if needle in (t.get("name") or "").lower()]


def shape_registry_describe_result(described: dict, *, table_filter: str | None = None) -> dict:
    """Envelope for vo_registry_describe.

    When `table_filter` is given, the table set is narrowed (case-insensitive
    substring over name/description) before shaping — a narrow filter yields a
    small set, so full per-column detail fits inline and the model gets exactly
    the tables it wants, with columns, in one call.

    Otherwise: small services pass through with full per-column detail for every
    table. Large services (tables x columns — e.g. Gaia/Data Lab) would overflow
    the model context, so the response degrades to a *table catalog*: every table
    keeps its name, (clipped) description, and column_count, but the per-column
    arrays are dropped. `truncated` discloses the degradation; a hint points the
    model at the per-table columns drill-down and at table_filter for narrowing.

    Always carries top-level `truncated` (project contract) and `total_tables`;
    `matched_tables` is added when a filter is applied.
    """
    out = dict(described)
    settings = get_settings()
    budget = settings.registry_describe_byte_limit

    all_tables = out.get("tables") or []
    total_tables = len(all_tables)
    out["total_tables"] = total_tables

    filtering = bool(table_filter and table_filter.strip())
    if filtering:
        working = _filter_describe_tables(all_tables, table_filter or "")
        out["tables"] = working
        out["matched_tables"] = len(working)
    else:
        working = all_tables

    if _estimate_payload_bytes(out) <= budget:
        out["truncated"] = False
        out["truncation_reason"] = None
        if filtering and not working:
            out["hints"] = [
                {
                    "kind": "tip",
                    "text": _no_match_hint(table_filter or "", total_tables),
                    "source": None,
                }
            ]
        return out

    catalog = [_describe_catalog_entry(t) for t in working]
    out["tables"] = catalog
    out["truncated"] = True
    out["truncation_reason"] = TRUNCATION_REASON_DESCRIBE_OVERSIZE
    # Placeholder hint so the fit measurement below includes its overhead; the
    # final text (with the real omitted count) is written once we know the count.
    out["hints"] = [
        {
            "kind": "tip",
            "text": _describe_hint(len(working), total_tables, table_filter),
            "source": None,
        }
    ]

    # Fit ladder. Table names are the irreducible discovery signal, so we keep
    # as many tables as possible and shed detail first:
    #   1. full catalog with descriptions,
    #   2. drop descriptions (names + counts are tiny),
    #   3. still too big (thousands of tables, e.g. Data Lab) -> trim the table
    #      count to the largest prefix that fits.
    if _estimate_payload_bytes(out) > budget:
        for entry in catalog:
            entry["description"] = None
    if _estimate_payload_bytes(out) > budget:
        catalog = _fit_tables(out, catalog, budget)
        out["tables"] = catalog

    tables_omitted = len(working) - len(catalog)
    out["hints"][0]["text"] = _describe_hint(tables_omitted, total_tables, table_filter)
    return out


def _describe_hint(tables_omitted: int, total_tables: int, table_filter: str | None) -> str:
    text = (
        "Per-column detail was omitted because this result exceeds the inline "
        "budget. To get one table's columns, call vo_tap_query with ADQL like "
        '"SELECT column_name, datatype, ucd, description FROM tap_schema.columns '
        "WHERE table_name = '<table>'\", or try vo_schema_describe for curated tables."
    )
    if tables_omitted > 0:
        text += f" {tables_omitted} table(s) were omitted from this catalog entirely."
    if table_filter and table_filter.strip():
        text += f" These are tables matching '{table_filter.strip()}' — refine table_filter to narrow further."
    else:
        text += (
            f" This service has {total_tables} tables; pass table_filter='<keyword>' "
            "to find specific tables (a narrow match returns their columns inline)."
        )
    return text


def _no_match_hint(table_filter: str, total_tables: int) -> str:
    return (
        f"No tables matched table_filter='{table_filter.strip()}'. This service has "
        f"{total_tables} tables — try a different keyword, or omit table_filter to list them."
    )


def _fit_tables(out: dict, catalog: list[dict], budget: int) -> list[dict]:
    """Largest prefix of `catalog` whose enclosing `out` payload fits `budget`.

    Binary search on the kept-table count. Mutates out['tables'] as a side
    effect of measuring; the caller assigns the returned list authoritatively.
    """
    lo, hi = 0, len(catalog)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        out["tables"] = catalog[:mid]
        if _estimate_payload_bytes(out) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return catalog[:lo]


def shape_promotion(
    *,
    job_url: str,
    archive: str,
    phase: str,
    submitted_at: datetime,
) -> dict[str, Any]:
    """Envelope returned when vo_tap_query goes async (explicit mode=async,
    auto-mode timeout fallback, or an oversize sync result).

    Shape-disjoint from the inline tabular envelope: there are no rows.
    The LLM branches on the literal `mode: "async"`.

    The upstream `job_url` is the job's only handle — pass it back to
    vo_tap_status / vo_tap_results / vo_tap_abort. There is deliberately no
    server-side job id: the server holds no per-job state, so nothing in this
    process can be reached by a caller who did not submit the job.
    """
    return {
        "mode": "async",
        "job_url": job_url,
        "phase": phase,
        "submitted_at": submitted_at.isoformat(),
        "archive": archive,
        "next_steps": [
            "Poll vo_tap_status(job_url) until phase is COMPLETED or ERROR — "
            "pass back the job_url from this response, verbatim.",
            "When COMPLETED, call vo_tap_results(job_url) to get the "
            "result_url and a fetch_recipe.",
            "Then execute the fetch_recipe code with your code-execution "
            "tool to load the data — do not abandon the job or re-submit "
            "the query.",
        ],
        "fetch_recipe": build_fetch_recipe(job_url),
    }
