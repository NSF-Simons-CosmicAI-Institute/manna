"""Shared dataclass→JSON-friendly-dict helper.

Covers the conversions the MCP envelope edge needs:
- tuples → lists (one level + nested)
- MappingProxyType → plain dict
- date → ISO string
- None / primitives pass through unchanged
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from types import MappingProxyType

import pytest

from manna._serialization import dataclass_to_jsonable_dict


@dataclass(frozen=True)
class _Sample:
    name: str
    tags: tuple[str, ...] = ()
    nested_pairs: tuple[tuple[str, str], ...] = ()
    extras: Mapping = field(default_factory=dict)
    when: date = date(2026, 6, 13)
    maybe: str | None = None


def test_tuple_of_strings_becomes_list():
    out = dataclass_to_jsonable_dict(_Sample(name="x", tags=("a", "b")))
    assert out["tags"] == ["a", "b"]


def test_nested_tuple_pairs_become_list_of_lists():
    out = dataclass_to_jsonable_dict(
        _Sample(name="x", nested_pairs=(("alma", "ivoa.obscore"),)),
    )
    assert out["nested_pairs"] == [["alma", "ivoa.obscore"]]


def test_mapping_proxy_type_becomes_plain_dict():
    extras = MappingProxyType({"enum": ("A", "B")})
    out = dataclass_to_jsonable_dict(_Sample(name="x", extras=extras))
    assert isinstance(out["extras"], dict)
    assert out["extras"] == {"enum": ["A", "B"]}


def test_date_becomes_iso_string():
    out = dataclass_to_jsonable_dict(_Sample(name="x", when=date(2026, 1, 2)))
    assert out["when"] == "2026-01-02"


def test_none_passes_through():
    out = dataclass_to_jsonable_dict(_Sample(name="x", maybe=None))
    assert out["maybe"] is None


def test_plain_string_passes_through():
    out = dataclass_to_jsonable_dict(_Sample(name="x"))
    assert out["name"] == "x"


def test_non_dataclass_input_raises_type_error():
    """Public contract: only dataclass instances are accepted."""
    with pytest.raises(TypeError, match="dataclass instance"):
        dataclass_to_jsonable_dict({"already": "a dict"})
    with pytest.raises(TypeError, match="dataclass instance"):
        dataclass_to_jsonable_dict("a string")
    with pytest.raises(TypeError, match="dataclass instance"):
        dataclass_to_jsonable_dict(_Sample)  # the class itself, not an instance
