"""IVOA tools (sync, inline tier).

One tool per IVOA standard, split by protocol:
* TAP: tools.tap (vo_tap_query)
* Cone Search: tools.cone (vo_cone_search)
* Simple Image Access: tools.sia (vo_sia_search)
* Registry: tools.registry (vo_registry_search, vo_registry_describe)
* Archive directory: tools.archives (vo_archive_list)
* Schema KB: tools.schema (vo_schema_describe)
* Target resolver: tools.resolver (vo_target_resolve)
"""

# Re-exports so `from manna.tools import vo_tap_query` still works.
from manna.tools.archives import vo_archive_list
from manna.tools.cone import vo_cone_search
from manna.tools.count import vo_count_observations
from manna.tools.find_observations import vo_find_observations
from manna.tools.inspect import vo_inspect_table
from manna.tools.registry import vo_registry_describe, vo_registry_search
from manna.tools.resolver import vo_target_resolve
from manna.tools.schema import vo_schema_describe
from manna.tools.sia import vo_sia_search
from manna.tools.survey import vo_survey_target
from manna.tools.tap import vo_tap_abort, vo_tap_query, vo_tap_results, vo_tap_status

__all__ = [
    "vo_archive_list",
    "vo_cone_search",
    "vo_count_observations",
    "vo_find_observations",
    "vo_inspect_table",
    "vo_registry_describe",
    "vo_registry_search",
    "vo_schema_describe",
    "vo_sia_search",
    "vo_survey_target",
    "vo_tap_abort",
    "vo_tap_query",
    "vo_tap_results",
    "vo_tap_status",
    "vo_target_resolve",
]
