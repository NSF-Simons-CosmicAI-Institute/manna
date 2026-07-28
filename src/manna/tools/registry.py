"""Tools for IVOA Registry."""

from typing import Annotated

from pydantic import Field

from manna.backends.registry import RegistryClient
from manna.errors import wrap_tool_errors
from manna.shaper import (
    shape_registry_describe_result,
    shape_registry_search_result,
)
from manna.tools._constants import _ERROR_DOCSTRING

_registry: RegistryClient | None = None


def _get_registry() -> RegistryClient:
    """Lazy accessor so tests can patch RegistryClient without import-time side effects."""
    global _registry
    if _registry is None:
        _registry = RegistryClient()
    return _registry


@wrap_tool_errors
def vo_registry_search(
    keywords: Annotated[
        list[str] | None,
        Field(
            description=(
                "Free-text keywords to match against service titles/descriptions. "
                "Example: ['Magellanic', 'photometry']."
            ),
            examples=[["magellanic"], ["RR Lyrae", "variable"]],
        ),
    ] = None,
    servicetype: Annotated[
        str | None,
        Field(
            description="Filter by service type: 'tap', 'sia', 'scs', 'ssa'.",
            examples=["tap", "sia"],
        ),
    ] = None,
    waveband: Annotated[
        str | None,
        Field(
            description=(
                "Filter by waveband: 'radio', 'infrared', 'optical', 'uv', "
                "'euv', 'x-ray', 'gamma-ray'."
            ),
            examples=["optical", "infrared"],
        ),
    ] = None,
    maxrec: Annotated[
        int,
        Field(ge=1, le=500, description="Hard cap on services returned. Default 50."),
    ] = 50,
) -> dict:
    """Discover IVOA-registered services matching the given constraints.

    Returns a {services: [...], row_count, truncated, truncation_reason}
    envelope. Each service entry has: ivoid, title, description, publisher,
    waveband, and one URL per capability (tap_url, sia_url, scs_url,
    ssa_url; null when the service doesn't expose that capability).

    Use for discovery before calling vo_tap_query / vo_sia_search /
    vo_cone_search on a specific endpoint. Smaller default maxrec (50)
    than catalog tools — discovery is about choice, not bulk data.
    """
    services = _get_registry().search(
        keywords=keywords, servicetype=servicetype, waveband=waveband, maxrec=maxrec
    )
    return shape_registry_search_result(services, maxrec=maxrec)


@wrap_tool_errors
def vo_registry_describe(
    ivoid_or_url: Annotated[
        str,
        Field(
            description=(
                "Either an IVOID (starts with 'ivo://') or a TAP service "
                "URL. The tool resolves both forms via RegTAP."
            ),
            examples=["ivo://eso.org/tap_obs", "https://datalab.noirlab.edu/tap"],
        ),
    ],
    table_filter: Annotated[
        str | None,
        Field(
            description=(
                "Optional case-insensitive keyword. When set, only tables whose "
                "name or description contains it are returned. Use this on large "
                "services (hundreds/thousands of tables) to find the ones you "
                "want AND get their columns in one call. Example: 'allwise', "
                "'gaia_source', 'obscore'."
            ),
            examples=["allwise", "gaia_source", "obscore"],
        ),
    ] = None,
) -> dict:
    """Introspect a specific IVOA service: its capabilities, and for TAP
    services its tables and columns.

    Returns {ivoid, title, description, capabilities, tables, truncated,
    total_tables} (plus matched_tables when table_filter is used). Use after
    vo_registry_search to learn what's queryable on a specific service before
    composing ADQL via vo_tap_query.

    Each table normally carries its full column list. For a very large service
    the response degrades to a table *catalog* (name + description +
    column_count per table, no per-column detail) and sets truncated: true.
    When that happens, either pass table_filter='<keyword>' to narrow to the
    tables you want (a narrow match returns their columns inline), or get one
    table's columns by querying tap_schema.columns WHERE table_name = '<table>'
    via vo_tap_query (or vo_schema_describe for curated tables). See the
    returned hints.
    """
    described = _get_registry().describe(ivoid_or_url=ivoid_or_url)
    return shape_registry_describe_result(described, table_filter=table_filter)


vo_registry_search.__doc__ = (vo_registry_search.__doc__ or "") + _ERROR_DOCSTRING
vo_registry_describe.__doc__ = (vo_registry_describe.__doc__ or "") + _ERROR_DOCSTRING
