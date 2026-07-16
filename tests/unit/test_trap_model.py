"""The Trap model — the declarative half of trap delivery (issue #57)."""

import pytest

from astro_archives_mcp.archives._audit import Audit
from astro_archives_mcp.archives._model import Note, Trap


def test_silent_trap_needs_no_triggers():
    t = Trap(kind="silent", guidance="use q3c_radial_query")
    assert t.triggers == ()
    # A silent trap is preventive — it is always shown, never matched.
    assert t.fires_on("SELECT anything") is False


def test_loud_trap_fires_case_insensitively():
    t = Trap(kind="loud", guidance="drop LOWER()", triggers=("LOWER(", "UPPER("))
    assert t.fires_on("select * from x where lower(name) = 'm87'") is True
    assert t.fires_on("SELECT * FROM x WHERE UPPER(name) = 'M87'") is True
    assert t.fires_on("SELECT * FROM x WHERE name = 'M87'") is False


def test_loud_trap_without_triggers_is_rejected():
    """A loud trap with nothing to match would never fire — that's a silent
    trap declared in the wrong channel, so fail loudly at construction."""
    with pytest.raises(ValueError, match="triggers"):
        Trap(kind="loud", guidance="x")


def test_silent_trap_with_triggers_is_rejected():
    with pytest.raises(ValueError, match="must not carry triggers"):
        Trap(kind="silent", guidance="x", triggers=("LOWER(",))


def test_unknown_kind_and_empty_guidance_rejected():
    with pytest.raises(ValueError, match="unknown trap kind"):
        Trap(kind="noisy", guidance="x")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="guidance"):
        Trap(kind="silent", guidance="")


def test_note_trap_is_optional_and_type_checked():
    audit = Audit.manual("n/a")
    assert Note(id="n", text="t", audit=audit).trap is None
    with pytest.raises(TypeError, match="must be a Trap"):
        Note(id="n", text="t", audit=audit, trap="silent")  # type: ignore[arg-type]
