"""Tool for surfacing the curated KNOWN_ARCHIVES registry to the LLM.

`vo_archive_list` is the agent-facing entry point into the project's
knowledge base of well-known IVOA archives. Each returned entry carries
the canonical endpoint URLs, capabilities, notable tables, and — most
importantly — `usage_notes` that capture archive-specific gotchas
(non-standard table locations, sync-vs-async routing, target-name
conventions, etc.).

The knowledge is now backed by per-archive modules (`archives/<name>.py`):
this tool surfaces the deployment's active archives via
`known_archives.active_archives()`, so it honors the `STABLE_ARCHIVES`
selection. An absent archive simply carries no curated claims — it stays
reachable via `vo_registry_search`. The tool contract is unchanged: per-table
`schemas` (served by `vo_schema_describe`) and the internal `priority` are not
echoed here.
"""

from typing import Annotated

from pydantic import Field

from astro_archives_mcp._serialization import dataclass_to_jsonable_dict
from astro_archives_mcp.errors import wrap_tool_errors
from astro_archives_mcp.known_archives import active_archives
from astro_archives_mcp.tools._constants import _ERROR_DOCSTRING


@wrap_tool_errors
def vo_archive_list(
    short_name: Annotated[
        str | None,
        Field(
            description=(
                "Optional. Return only the archive with this short_name "
                "(case-insensitive), e.g. 'nrao'. Use this when you already "
                "know which archive you want — it returns a single entry "
                "instead of the full set, saving context. Unknown names "
                "return an empty list (count: 0)."
            ),
            examples=["nrao", "datalab", "alma"],
        ),
    ] = None,
    waveband: Annotated[
        str | None,
        Field(
            description=(
                "Optional. Return only archives in this waveband "
                "(case-insensitive), e.g. 'radio', 'optical', 'millimeter'. "
                "Combines with short_name (both must match)."
            ),
            examples=["radio", "optical", "millimeter"],
        ),
    ] = None,
) -> dict:
    """List the IVOA archives this server has first-class knowledge of.

    Each entry includes the archive's endpoint URLs (TAP / SIA / SCS),
    waveband, description, notable tables, and **usage_notes** — short
    agent-facing strings capturing archive-specific gotchas like
    non-standard table locations, sync-vs-async routing recommendations,
    target-name conventions, and ADQL quirks.

    Call this FIRST when planning a query against an archive whose
    behavior you don't already know — it'll save you the trial-and-error
    of discovering quirks through failed queries. The notes are curated
    based on real friction encountered while building the server.

    Pass `short_name` and/or `waveband` to narrow the result. With no
    arguments it returns every known archive (the usage_notes are verbose,
    so prefer `short_name` once you know which archive you need).

    Archives not listed here still work via `vo_registry_search` followed
    by `vo_registry_describe` / `vo_tap_query` — this tool only covers the
    well-known set.

    Returns:
        {
          "archives": [
            {
              "short_name": "...",
              "display_name": "...",
              "host_substrings": ["..."],
              "tap_url": "...",
              "sia_url": "..." | null,
              "scs_url": "..." | null,
              "waveband": "...",
              "description": "...",
              "notable_tables": ["..."],
              "usage_notes": [
                "Short agent-facing strings — read these BEFORE composing "
                "a query. They capture real gotchas like non-standard "
                "table names, required mode='async' routing, target-name "
                "aliasing, etc."
              ]
            },
            ...
          ],
          "count": N
        }
    """
    selected = active_archives()
    if short_name is not None:
        sn = short_name.strip().lower()
        selected = tuple(a for a in selected if a.short_name.lower() == sn)
    if waveband is not None:
        wb = waveband.strip().lower()
        selected = tuple(a for a in selected if (a.waveband or "").lower() == wb)

    # `schemas` (surfaced by vo_schema_describe) and the internal ordering
    # `priority` are not part of this tool's contract — drop them so the
    # archive-list envelope stays the identity/usage_notes view it always was.
    archives = []
    for a in selected:
        d = dataclass_to_jsonable_dict(a)
        d.pop("schemas", None)
        d.pop("priority", None)
        archives.append(d)
    return {"archives": archives, "count": len(archives)}


vo_archive_list.__doc__ = (vo_archive_list.__doc__ or "") + _ERROR_DOCSTRING
