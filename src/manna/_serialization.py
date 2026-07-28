"""Shared dataclass → JSON-friendly dict helper.

Used by tools whose envelope is built from a frozen dataclass: turns
tuples (any nesting depth, including 2-tuples-in-a-tuple) into lists,
MappingProxyType into plain dict, and date into ISO 8601 string.
Everything else passes through unchanged.

`dataclasses.asdict` is unusable here because its internal `deepcopy`
call fails on `MappingProxyType` (the proxy isn't picklable). Walking
`fields()` ourselves avoids the deepcopy and keeps the conversion
explicit. The recursive `_jsonable` also preserves tuple-as-list and
date-as-ISO-string semantics, both of which `asdict` gets wrong for
our MCP envelope edge.
"""

from dataclasses import fields, is_dataclass
from datetime import date
from types import MappingProxyType
from typing import Any


def _jsonable(value: Any) -> Any:
    # MappingProxyType is matched before dict because it is NOT a
    # subclass of dict (it's a collections.abc.Mapping). Keeping the
    # check up here makes the proxy-handling intent explicit even
    # though swapping the order wouldn't change behaviour.
    if isinstance(value, (MappingProxyType, dict)):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(v) for v in value]
    if isinstance(value, date):
        return value.isoformat()
    return value


def dataclass_to_jsonable_dict(obj: Any) -> dict[str, Any]:
    """Convert a frozen dataclass into a JSON-friendly dict.

    Recursively converts tuples → lists, MappingProxyType → dict, and
    date → ISO string. Plain primitives pass through. `obj` MUST be a
    dataclass instance.
    """
    # `is_dataclass` returns True for both classes and instances; we
    # explicitly require an instance so callers don't accidentally pass
    # the class object.
    if not is_dataclass(obj) or isinstance(obj, type):
        raise TypeError(
            f"dataclass_to_jsonable_dict expects a dataclass instance; got {type(obj).__name__}"
        )
    return {f.name: _jsonable(getattr(obj, f.name)) for f in fields(obj)}
