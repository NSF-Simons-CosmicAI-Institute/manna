"""Sphinx extension: render MANNA's tool reference from the live server.

``collect_tools()`` boots the FastMCP server in-process, lists its tools
through fastmcp's in-memory ``Client``, and returns plain dataclasses. The
``manna-tools`` directive renders them as MyST. Nothing is generated into the
source tree, so the reference cannot drift from the registered tools.

The one editorial input is ``LAYERS``: which of the paper's four layers each
tool belongs to (Connections / Shortcut tools / Result handling / Archive
notes). ``tests/unit/test_docs_tool_reference.py`` asserts it names exactly
the registered tools.

``docutils`` (part of the ``docs`` dependency group, not ``dev``) is only
needed by the actual Sphinx directive below, so its import is guarded — the
test module imports the pure dataclasses/functions above it and must not
require ``uv sync --group docs`` to run in the base ``test`` CI job.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from fastmcp import Client

from manna.app import build_mcp
from manna.tools._constants import _ERROR_DOCSTRING

try:
    from docutils import nodes
    from docutils.parsers.rst import Directive
    from docutils.statemachine import StringList
except ImportError:  # pragma: no cover - exercised only without `--group docs`
    nodes = None  # type: ignore[assignment]
    StringList = None  # type: ignore[assignment]
    Directive = object  # type: ignore[assignment]

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
    annotations: dict[str, bool]


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


def _strip_error_tail(description: str) -> str:
    tail = _ERROR_DOCSTRING.strip()
    return description.replace(tail, "").rstrip()


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
                description=_strip_error_tail(t.description or ""),
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
                ex = ", ".join(f"`{e}`" for e in p.examples)
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


class MannaToolsDirective(Directive):
    """``.. manna-tools::`` — render every registered tool as MyST markdown."""

    has_content = False

    def run(self):
        lines: list[str] = []
        for doc in collect_tools():
            lines += _render_tool(doc)
        node = nodes.section()
        node.document = self.state.document
        self.state.nested_parse(StringList(lines, source="manna-tools"), 0, node)
        return node.children


def setup(app):
    app.add_directive("manna-tools", MannaToolsDirective)
    return {"version": "1.0", "parallel_read_safe": False}
