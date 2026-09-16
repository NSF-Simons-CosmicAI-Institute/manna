"""The docs' generated tool reference must cover every registered tool.

docs/_ext/_collect.py introspects the live FastMCP server at build time.
This test imports its pure collector (no docutils import, so it runs without
`uv sync --group docs`) so a tool added without a description, or a parameter
added without one, fails here rather than as a Sphinx warning.
"""

import re
import sys
from pathlib import Path

import pytest

from manna.tools import __all__ as REGISTERED_TOOL_NAMES
from manna.tools._constants import _ERROR_DOCSTRING

_EXT_DIR = Path(__file__).resolve().parents[2] / "docs" / "_ext"
sys.path.insert(0, str(_EXT_DIR))

from _collect import LAYERS, ParamDoc, ToolDoc, _render_tool, collect_tools  # noqa: E402


@pytest.fixture(scope="module")
def tool_docs():
    return {t.name: t for t in collect_tools()}


def test_every_registered_tool_is_documented(tool_docs):
    assert set(tool_docs) == set(REGISTERED_TOOL_NAMES)


def test_every_tool_has_a_layer_and_a_description(tool_docs):
    for name, doc in tool_docs.items():
        assert doc.layers, f"{name} has no layer tag in LAYERS"
        assert doc.description.strip(), f"{name} has an empty description"


def test_shared_error_tail_is_stripped(tool_docs):
    tail = _ERROR_DOCSTRING.strip()
    for name, doc in tool_docs.items():
        assert tail not in doc.description, f"{name} still carries the shared error tail"


def test_every_parameter_has_a_description(tool_docs):
    for name, doc in tool_docs.items():
        for p in doc.params:
            assert p.description.strip(), f"{name}.{p.name} has no description"


def test_description_prose_is_not_rendered_as_a_code_block(tool_docs):
    """MyST reads 4+ leading spaces as an indented code block.

    FastMCP passes `fn.__doc__` raw (first line flush, later lines carrying
    the function body's four-space indent), so an unprocessed description
    renders as one giant `<pre>`. A line is allowed to start with four+
    spaces only when it is a deliberate code/JSON block, signalled by the
    preceding non-blank line ending in `:` (e.g. `Returns:`). A four-space
    continuation of a bullet-list item (aligned under that item's own text,
    e.g. under `  * `columns`: ...`) is also allowed — CommonMark/MyST
    renders that as list-item text, not a code block.
    """
    list_marker = re.compile(r"^\s*(?:[-*+]|\d+\.)\s")
    for name, doc in tool_docs.items():
        lines = doc.description.split("\n")
        preceding_non_blank = ""
        in_code_block = False
        for line in lines[1:]:
            if not line.strip():
                continue
            if line.startswith("    "):
                if not in_code_block:
                    allowed = preceding_non_blank.rstrip().endswith(":") or list_marker.match(
                        preceding_non_blank
                    )
                    assert allowed, f"{name}: prose line rendered as a code block: {line!r}"
                in_code_block = True
            else:
                in_code_block = False
            preceding_non_blank = line


def test_layers_map_names_only_real_tools():
    assert set(LAYERS) == set(REGISTERED_TOOL_NAMES)


def test_abort_is_the_only_non_read_only_tool(tool_docs):
    non_read_only = {n for n, d in tool_docs.items() if d.annotations.get("readOnlyHint") is False}
    assert non_read_only == {"abort_async_job"}


def test_union_typed_parameter_row_has_five_cells():
    """A `string | null`-style type must not split the markdown table row.

    `_render_tool` builds one `| ... | ... | ... | ... | ... |` row per
    parameter. `_json_type` legitimately produces types containing `|`
    (e.g. `string | null`, `"sync" | "async" | "auto"`); those pipes must be
    escaped like the description's, or the row splits into extra cells and
    the description is lost off the end.
    """
    doc = ToolDoc(
        name="example_tool",
        layers=("Connections",),
        description="An example tool for the regression test.",
        params=(
            ParamDoc(
                name="mode",
                type='"sync" | "async" | "auto"',
                required=False,
                default='"auto"',
                description="How to run the query.",
                examples=(),
            ),
            ParamDoc(
                name="short_name",
                type="string | null",
                required=False,
                default=None,
                description="Restrict to one archive.",
                examples=(),
            ),
        ),
        annotations={},
    )
    rows = [line for line in _render_tool(doc) if line.startswith("| `")]
    assert rows, "expected at least one rendered parameter row"
    for row in rows:
        cells = re.split(r"(?<!\\)\|", row)
        assert len(cells) - 2 == 5, f"row split into {len(cells) - 2} cells: {row!r}"
    assert any("How to run the query." in row for row in rows)
    assert any("Restrict to one archive." in row for row in rows)
