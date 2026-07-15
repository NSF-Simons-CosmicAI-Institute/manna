"""Tool for querying the curated per-table schema knowledge base.

`vo_schema_describe(archive, table)` returns table-specific structured
facts (missing ObsCore columns, enum values, spatial index columns) that
the agent can use before composing an ADQL query. Archive-level quirks
(ADQL bugs, mode requirements) are in vo_archive_list instead.

Soft-fails on miss (returns `known: false`) so the LLM cleanly falls
back to `vo_registry_describe` for archives/tables not yet curated.
"""

from typing import Annotated

from pydantic import Field

from astro_archives_mcp.archives.knowledge import lookup_schema, schema_to_dict
from astro_archives_mcp.errors import ValidationError, wrap_tool_errors
from astro_archives_mcp.tools._constants import _ERROR_DOCSTRING


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
    """Curated quirks for one archive table. Augments live introspection.

    Returns table-specific structured facts: missing standard columns,
    value enums for filterable fields, notes, and cross_refs to related
    tables. On miss returns `{"known": false, "archive": ..., "table": ...}`
    with no other keys — fall back to `vo_registry_describe` for the full
    schema.
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
        return {
            "known": False,
            "archive": archive_clean,
            "table": table_clean,
        }

    return {
        "known": True,
        **schema_to_dict(s),
    }


vo_schema_describe.__doc__ = (vo_schema_describe.__doc__ or "") + _ERROR_DOCSTRING
