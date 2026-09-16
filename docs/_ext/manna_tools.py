"""Sphinx extension: the ``manna-tools`` directive.

Renders MANNA's tool reference as MyST by delegating to ``_collect.py``,
which introspects the live FastMCP server and returns plain dataclasses.
Nothing is generated into the source tree, so the reference cannot drift
from the registered tools.

This module only holds the docutils-facing directive and ``setup()``. The
pure collection logic (dataclasses, ``LAYERS``, rendering) lives in
``_collect.py`` so it can be imported by
``tests/unit/test_docs_tool_reference.py`` without pulling in ``docutils``,
which is part of the ``docs`` dependency group, not ``dev``.
"""

from __future__ import annotations

from _collect import _render_tool, collect_tools
from docutils import nodes
from docutils.parsers.rst import Directive
from docutils.statemachine import StringList


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
    return {"version": "1.0", "parallel_read_safe": True, "parallel_write_safe": True}
