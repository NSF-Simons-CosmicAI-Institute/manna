"""IVOA tools (sync, inline tier).

One tool per IVOA standard, split by protocol:
* TAP: tools.tap (run_adql_query, get_async_job_status, get_async_job_results, abort_async_job)
* Cone Search: tools.cone (search_catalog_by_position)
* Simple Image Access: tools.sia (search_images_by_position)
* Registry: tools.registry (search_ivoa_registry, describe_ivoa_service)
* Archive directory: tools.archives (list_archives)
* Per-table archive notes: tools.schema (describe_table)
* Target resolver: tools.resolver (resolve_target_name)

Shortcut tools (bundle a multi-step task into one call):
* tools.shortcuts.count (count_observations_near_target)
* tools.shortcuts.survey (survey_archives_for_target)
* tools.inspect (preview_table)
* tools.shortcuts.find_observations (find_observations_of_target)
"""

# Re-exports so `from manna.tools import run_adql_query` still works.
from manna.tools.archives import list_archives
from manna.tools.cone import search_catalog_by_position
from manna.tools.inspect import preview_table
from manna.tools.registry import describe_ivoa_service, search_ivoa_registry
from manna.tools.resolver import resolve_target_name
from manna.tools.schema import describe_table
from manna.tools.shortcuts.count import count_observations_near_target
from manna.tools.shortcuts.find_observations import find_observations_of_target
from manna.tools.shortcuts.survey import survey_archives_for_target
from manna.tools.sia import search_images_by_position
from manna.tools.tap import (
    abort_async_job,
    get_async_job_results,
    get_async_job_status,
    run_adql_query,
)

__all__ = [
    "list_archives",
    "search_catalog_by_position",
    "count_observations_near_target",
    "find_observations_of_target",
    "preview_table",
    "describe_ivoa_service",
    "search_ivoa_registry",
    "describe_table",
    "search_images_by_position",
    "survey_archives_for_target",
    "abort_async_job",
    "run_adql_query",
    "get_async_job_results",
    "get_async_job_status",
    "resolve_target_name",
]

# The registered tool names, as MCP clients see them. Evals use this (via
# evals._common.is_manna_tool) to tell MANNA calls from a harness's built-ins.
TOOL_NAMES: frozenset[str] = frozenset(__all__)
