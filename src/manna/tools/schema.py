"""Tool for querying the curated per-table schema knowledge base.

`vo_schema_describe(archive, table)` returns table-specific structured
facts (missing ObsCore columns, enum values, spatial index columns) that
the agent can use before composing an ADQL query. Archive-level quirks
(ADQL bugs, mode requirements) are in vo_archive_list instead.

It also returns the table's **real column list**, fetched live from the
archive's `tap_schema.columns`. That used to be missing, which made this tool
actively harmful: the curated notes told the model "always project an explicit
column list" while supplying neither the columns nor a route to them, so a model
that obeyed had to invent column names. The pointer to `vo_registry_describe`
existed only on the miss path, so the better-curated a table was, the blinder the
model got.

If the fetch fails the payload carries `column_list_recipe` instead — the exact
query to run. Whenever the archive's TAP endpoint is known, exactly one of
`columns` / `column_list_recipe` is present. For an archive we have no endpoint
for there is nothing to ask and no recipe worth offering, so the miss envelope
stays bare.

Soft-fails on miss (returns `known: false`) — that means only "no curated notes",
not "no such table"; the column list is still returned for a known archive.
"""

from typing import Annotated

from pydantic import Field

from manna.archives._endpoints import by_short_name
from manna.archives._knowledge import lookup_schema, schema_to_dict
from manna.backends.tap import TapClient
from manna.config import get_settings
from manna.errors import ValidationError, wrap_tool_errors
from manna.tools._constants import _ERROR_DOCSTRING

_tap: TapClient | None = None

# Wide catalog tables run ~100 columns; obscore ~75. Slack, not a real bound.
_COLUMN_MAXREC = 1000


def _get_tap() -> TapClient:
    """Lazy accessor so tests can patch TapClient without import-time side effects."""
    global _tap
    if _tap is None:
        _tap = TapClient(sync_timeout_seconds=get_settings().tap_sync_timeout_seconds)
    return _tap


def _column_recipe(table: str) -> str:
    """The exact query that lists a table's columns.

    The table name MUST be fully qualified. Verified on Data Lab:
    table_name='object' returns 0 rows with NO error, while
    table_name='nsc_dr2.object' returns 99. A recipe that dropped the schema
    prefix would be worse than no recipe at all.
    """
    return f"SELECT column_name, datatype FROM tap_schema.columns WHERE table_name = '{table}'"


def _fetch_columns(endpoint: str, table: str) -> list[dict] | None:
    """Live column list for one table, or None if the archive could not answer.

    None means "we could not look" — the caller degrades to the recipe. An empty
    list means "we looked and there are none", which is a real answer: usually a
    wrong table name, since Data Lab returns 0 rows rather than erroring on one.

    `datatype` is passed through verbatim. The archives disagree (datalab
    'adql:DOUBLE', alma 'int', nrao 'votable:char' — different TAP_SCHEMA
    versions) and an LLM reads all three fine, so normalizing would buy nothing
    while adding a mapping to maintain and a way to be wrong about a type.
    """
    try:
        rows = _get_tap().query(
            endpoint=endpoint, adql=_column_recipe(table), maxrec=_COLUMN_MAXREC
        )
    except Exception:  # noqa: BLE001 - any failure degrades to the recipe
        return None
    return [{"name": str(row[0]), "datatype": str(row[1])} for row in rows]


def _attach_columns(payload: dict, *, archive: str, table: str) -> dict:
    """Add the real column list, or the recipe to fetch it, to a payload."""
    known_archive = by_short_name(archive)
    endpoint = known_archive.tap_url if known_archive else None
    if not endpoint:
        # No endpoint to ask, and a recipe naming an archive we can't identify is
        # noise. Leave the miss envelope bare; vo_archive_list is the way out.
        return payload

    columns = _fetch_columns(endpoint, table)
    if columns is None:
        payload["column_list_recipe"] = _column_recipe(table)
        return payload

    payload["columns"] = columns
    if not columns:
        payload["hint"] = (
            f"No columns found for table_name = '{table}'. The name must be fully "
            "qualified as it appears in the archive's TAP schema (e.g. "
            "'nsc_dr2.object', not 'object') — an unqualified name returns an empty "
            "list rather than an error. Use vo_registry_describe to list the "
            "archive's tables."
        )
    return payload


@wrap_tool_errors
def vo_schema_describe(
    archive: Annotated[
        str,
        Field(
            description=(
                "Archive short_name (e.g. 'nrao', 'datalab', 'alma'). "
                "Use vo_archive_list to discover available names."
            ),
            examples=["nrao", "datalab", "alma"],
        ),
    ],
    table: Annotated[
        str,
        Field(
            description=(
                "Fully qualified table name as it appears in the "
                "archive's TAP schema (e.g. 'tap_schema.obscore', "
                "'ivoa.obscore', 'nsc_dr2.object')."
            ),
            examples=["tap_schema.obscore", "ivoa.obscore", "nsc_dr2.object"],
        ),
    ],
) -> dict:
    """Curated quirks + the real column list for one archive table.

    Returns the table's actual columns (name + datatype, fetched live from the
    archive's tap_schema.columns) alongside table-specific curated facts:
    missing standard columns, value enums for filterable fields, notes, and
    cross_refs to related tables.

    For a known archive, exactly one of these is always present:
      * `columns`: [{"name": ..., "datatype": ...}] — the real column list.
        Project these explicitly rather than SELECT *.
      * `column_list_recipe`: the query to run yourself, if the fetch failed.

    `known: false` means only that we carry no curated notes for the table — for
    a known archive the column list is still returned. Use `vo_registry_describe`
    to discover which tables an archive has, or `vo_archive_list` for valid
    archive short_names.
    """
    archive_clean = archive.strip()
    table_clean = table.strip()
    if not archive_clean or not table_clean:
        raise ValidationError(
            message=(
                "Both 'archive' and 'table' must be non-empty. Use "
                "vo_archive_list to discover archive short_names."
            ),
        )

    s = lookup_schema(archive=archive_clean, table=table_clean)
    if s is None:
        payload = {
            "known": False,
            "archive": archive_clean,
            "table": table_clean,
        }
    else:
        payload = {
            "known": True,
            **schema_to_dict(s),
        }

    return _attach_columns(payload, archive=archive_clean, table=table_clean)


vo_schema_describe.__doc__ = (vo_schema_describe.__doc__ or "") + _ERROR_DOCSTRING
