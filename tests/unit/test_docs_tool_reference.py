"""The docs' generated tool reference must cover every registered tool.

docs/_ext/manna_tools.py introspects the live FastMCP server at build time.
This test imports its pure collector so a tool added without a description,
or a parameter added without one, fails here rather than as a Sphinx warning.
"""

import sys
from pathlib import Path

import pytest

from manna.tools import __all__ as REGISTERED_TOOL_NAMES
from manna.tools._constants import _ERROR_DOCSTRING

_EXT_DIR = Path(__file__).resolve().parents[2] / "docs" / "_ext"
sys.path.insert(0, str(_EXT_DIR))

from manna_tools import LAYERS, collect_tools  # noqa: E402


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


def test_layers_map_names_only_real_tools():
    assert set(LAYERS) == set(REGISTERED_TOOL_NAMES)


def test_abort_is_the_only_non_read_only_tool(tool_docs):
    non_read_only = {n for n, d in tool_docs.items() if d.annotations.get("readOnlyHint") is False}
    assert non_read_only == {"abort_async_job"}
