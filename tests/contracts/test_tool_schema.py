"""Contract tests for the LLM-facing tool surface.

These tests enforce conventions every registered tool must follow:
- Non-empty docstring (the LLM sees this as the tool's description).
- All parameters annotated with `Annotated[..., Field(...)]`.
- Every `Field` has a non-empty description.
- String fields surfacing endpoints/URLs/identifiers must have at least
  one example (LLM picks better URLs when given concrete options).
- The tool's name is `vo_*` (project convention).

When a new tool gets added or an existing one gets edited, these tests
catch drift before the LLM sees it.
"""

import inspect
from typing import Annotated, get_args, get_origin, get_type_hints

import pytest
from pydantic.fields import FieldInfo

from astro_archives_mcp.app import build_mcp
from astro_archives_mcp.tools import __all__ as REGISTERED_TOOL_NAMES
from astro_archives_mcp.tools import (
    vo_archive_list,
    vo_cone_search,
    vo_registry_describe,
    vo_registry_search,
    vo_schema_describe,
    vo_sia_search,
    vo_tap_abort,
    vo_tap_query,
    vo_tap_results,
    vo_tap_status,
    vo_target_resolve,
)

ALL_TOOLS = (
    vo_archive_list,
    vo_cone_search,
    vo_registry_describe,
    vo_registry_search,
    vo_schema_describe,
    vo_sia_search,
    vo_tap_abort,
    vo_tap_query,
    vo_tap_results,
    vo_tap_status,
    vo_target_resolve,
)


def _unwrap(fn):
    """Strip `wrap_tool_errors` and similar decorators to reach the raw
    callable whose annotations we want to inspect."""
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__
    return fn


def _extract_field_info(annotation) -> FieldInfo | None:
    """Return the `Field(...)` info attached to an `Annotated[...]` type, if any."""
    if get_origin(annotation) is not Annotated:
        return None
    for meta in get_args(annotation)[1:]:
        if isinstance(meta, FieldInfo):
            return meta
    return None


# ---------- registration completeness ----------


def _registered_tool_names() -> set[str]:
    """Enumerate the tools FastMCP actually exposes."""
    import asyncio

    mcp = build_mcp()
    tools = asyncio.run(mcp.list_tools())
    return {t.name for t in tools}


def test_every_tool_in_dunder_all_is_registered_in_build_mcp():
    """If you add a tool to `tools/__init__.py.__all__` you must also
    register it in `build_mcp()`."""
    registered = _registered_tool_names()
    declared = set(REGISTERED_TOOL_NAMES)
    missing = declared - registered
    assert not missing, (
        f"Tools declared in tools/__init__.__all__ but not registered "
        f"in build_mcp(): {sorted(missing)}"
    )


def test_all_registered_tools_use_vo_prefix():
    """Project convention: every tool name starts with `vo_`."""
    for name in _registered_tool_names():
        assert name.startswith("vo_"), f"Tool {name!r} does not follow the vo_* naming convention"


# ---------- docstring presence ----------


@pytest.mark.parametrize("tool", ALL_TOOLS, ids=lambda t: t.__name__)
def test_tool_has_non_empty_docstring(tool):
    """The LLM reads the tool docstring as its `description`. Empty
    docstring = silent tool in the schema."""
    raw = _unwrap(tool)
    doc = (raw.__doc__ or "").strip()
    assert len(doc) >= 30, (
        f"{tool.__name__} has a {len(doc)}-char docstring; need at least 30 to be useful to the LLM"
    )


# ---------- parameter field info ----------


@pytest.mark.parametrize("tool", ALL_TOOLS, ids=lambda t: t.__name__)
def test_every_parameter_has_a_field_description(tool):
    """Every parameter must be `Annotated[T, Field(description=...)]`
    with a non-empty description. Pydantic Fields without descriptions
    show up in the schema as bare types with no LLM guidance."""
    raw = _unwrap(tool)
    sig = inspect.signature(raw)
    hints = get_type_hints(raw, include_extras=True)
    failures: list[str] = []
    for param_name, _param in sig.parameters.items():
        ann = hints.get(param_name)
        if ann is None:
            failures.append(f"{param_name}: no type annotation")
            continue
        info = _extract_field_info(ann)
        if info is None:
            failures.append(f"{param_name}: type annotation must be Annotated[T, Field(...)]")
            continue
        desc = (info.description or "").strip()
        if not desc:
            failures.append(f"{param_name}: Field has empty description")
    assert not failures, f"{tool.__name__} parameter contract violations:\n  " + "\n  ".join(
        failures
    )


# ---------- examples on URL-shaped string fields ----------

_URL_FIELD_NAMES = {"endpoint", "access_url", "ivoid_or_url"}


@pytest.mark.parametrize("tool", ALL_TOOLS, ids=lambda t: t.__name__)
def test_url_fields_have_at_least_one_example(tool):
    """For fields that take a URL or service IVOID, the LLM has nothing
    to ground itself on without `examples=[...]`. Forcing this catches
    the common case of someone adding a new endpoint-taking tool and
    forgetting examples."""
    raw = _unwrap(tool)
    hints = get_type_hints(raw, include_extras=True)
    failures: list[str] = []
    for param_name, ann in hints.items():
        if param_name == "return":
            continue
        if param_name not in _URL_FIELD_NAMES:
            continue
        info = _extract_field_info(ann)
        if info is None:
            continue
        examples = info.examples or []
        if not examples:
            failures.append(
                f"{param_name}: URL-shaped field has no examples; LLM has "
                "nothing concrete to ground on"
            )
    assert not failures, (
        f"{tool.__name__} URL-field example contract violations:\n  " + "\n  ".join(failures)
    )
