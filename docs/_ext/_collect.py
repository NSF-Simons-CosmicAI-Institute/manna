"""Pure collector for MANNA's generated tool reference.

Boots the FastMCP server in-process, lists its tools through fastmcp's
in-memory ``Client``, and returns plain dataclasses describing each one. No
``docutils`` import here — this module is imported directly by
``tests/unit/test_docs_tool_reference.py``, which must run in the base
``test`` CI job without ``uv sync --group docs``. The Sphinx directive that
renders these dataclasses as MyST lives in ``manna_tools.py``.

The one editorial input is ``LAYERS``: which of the paper's four layers each
tool belongs to (Connections / Shortcut tools / Result handling / Archive
notes). ``tests/unit/test_docs_tool_reference.py`` asserts it names exactly
the registered tools.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

from fastmcp import Client

from manna.app import build_mcp
from manna.tools._constants import _ERROR_DOCSTRING

LAYERS: dict[str, tuple[str, ...]] = {
    "list_archives": ("Archive notes",),
    "describe_table": ("Archive notes",),
    "resolve_target_name": ("Connections",),
    "run_adql_query": ("Connections", "Result handling"),
    "get_async_job_status": ("Connections",),
    "get_async_job_results": ("Connections", "Result handling"),
    "abort_async_job": ("Connections",),
    "search_ivoa_registry": ("Connections",),
    "describe_ivoa_service": ("Connections", "Result handling"),
    "search_catalog_by_position": ("Connections", "Result handling"),
    "search_images_by_position": ("Connections", "Result handling"),
    "find_observations_of_target": ("Shortcut tools",),
    "count_observations_near_target": ("Shortcut tools",),
    "survey_archives_for_target": ("Shortcut tools",),
    "preview_table": ("Shortcut tools", "Archive notes"),
}


@dataclass(frozen=True)
class ParamDoc:
    name: str
    type: str
    required: bool
    default: str | None
    description: str
    examples: tuple[str, ...]


@dataclass(frozen=True)
class ToolDoc:
    name: str
    layers: tuple[str, ...]
    description: str
    params: tuple[ParamDoc, ...]
    annotations: dict[str, object]


def _json_type(schema: dict[str, Any]) -> str:
    """Human-readable type for one JSON-schema property."""
    if "anyOf" in schema:
        return " | ".join(_json_type(s) for s in schema["anyOf"])
    if "enum" in schema:
        return " | ".join(json.dumps(v) for v in schema["enum"])
    t = schema.get("type")
    if isinstance(t, list):
        return " | ".join(t)
    if t == "array":
        return f"array of {_json_type(schema.get('items', {}))}"
    return t or "any"


def _clean_description(description: str) -> str:
    """Strip the shared error tail, then dedent for MyST prose rendering.

    FastMCP passes ``fn.__doc__`` raw: the first line sits flush left and
    every later line carries the docstring's original four-space function
    body indent. MyST reads four-or-more leading spaces as an indented code
    block, so left alone every multi-line description rendered as one
    preformatted block.

    ``inspect.cleandoc``-style common-prefix dedent does not work here:
    ``run_adql_query``'s description has the up-front-note cheatsheet
    appended at column 0 (see ``app._tap_query_description``), which drags
    the common indent to zero and makes a full dedent a no-op. Instead this
    strips exactly one four-space level from every line after the first.
    A seven-space continuation (a docstring sub-list item) lands at three
    spaces, below the code-block threshold, and renders as prose. An
    eight-space ``Returns:`` JSON sketch line lands at four spaces and
    correctly stays a code block.
    """
    tail = _ERROR_DOCSTRING.strip()
    cleaned = description.replace(tail, "").rstrip()
    first, _, rest = cleaned.partition("\n")
    if not rest:
        return first
    rest = re.sub(r"(?m)^ {4}", "", rest)
    return f"{first}\n{rest}"


def _param_docs(input_schema: dict[str, Any]) -> tuple[ParamDoc, ...]:
    required = set(input_schema.get("required", []))
    out: list[ParamDoc] = []
    for name, prop in input_schema.get("properties", {}).items():
        default = prop.get("default")
        out.append(
            ParamDoc(
                name=name,
                type=_json_type(prop),
                required=name in required,
                default=None if name in required or default is None else json.dumps(default),
                description=prop.get("description", ""),
                examples=tuple(str(e) for e in prop.get("examples", [])),
            )
        )
    return tuple(out)


async def _list_tools():
    async with Client(build_mcp()) as client:
        return await client.list_tools()


def collect_tools() -> list[ToolDoc]:
    """Introspect the server and return one ToolDoc per registered tool."""
    tools = asyncio.run(_list_tools())
    docs: list[ToolDoc] = []
    for t in tools:
        ann = t.annotations.model_dump(exclude_none=True) if t.annotations else {}
        docs.append(
            ToolDoc(
                name=t.name,
                layers=LAYERS.get(t.name, ()),
                description=_clean_description(t.description or ""),
                params=_param_docs(t.inputSchema or {}),
                annotations=ann,
            )
        )
    docs.sort(key=lambda d: list(LAYERS).index(d.name) if d.name in LAYERS else 999)
    return docs


def _render_tool(doc: ToolDoc) -> list[str]:
    lines = [f"## `{doc.name}`", ""]
    tags = " · ".join(doc.layers) if doc.layers else "—"
    flags = ", ".join(f"`{k}`" for k, v in doc.annotations.items() if v is True) or "none"
    lines += [f"**Layer:** {tags}  ", f"**Annotations:** {flags}", ""]
    lines += [doc.description, ""]
    if doc.params:
        lines += [
            "| Parameter | Type | Required | Default | Description |",
            "|---|---|---|---|---|",
        ]
        for p in doc.params:
            desc = p.description.replace("|", "\\|").replace("\n", " ")
            if p.examples:
                ex = ", ".join(f"`{e.replace('|', '\\|')}`" for e in p.examples)
                desc = f"{desc} Examples: {ex}."
            ptype = p.type.replace("|", "\\|")
            default = f"`{p.default.replace('|', '\\|')}`" if p.default is not None else "—"
            lines.append(
                f"| `{p.name}` | `{ptype}` | {'yes' if p.required else 'no'} | {default} | {desc} |"
            )
        lines.append("")
    else:
        lines += ["*No parameters.*", ""]
    return lines
