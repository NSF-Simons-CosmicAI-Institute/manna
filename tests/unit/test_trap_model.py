"""The Trap model — the declarative half of trap delivery (issue #57).

Loudness is carried entirely by `triggers`: none ⇒ silent (preventive, always
shown), some ⇒ loud (reactive, fires on a matching ADQL).
"""

import pytest

from manna.archives._audit import Audit
from manna.archives._model import Note, Trap


def test_triggerless_trap_is_silent_and_never_fires():
    t = Trap(guidance="use q3c_radial_query")
    assert t.is_loud is False
    # A silent trap is preventive — it is always shown, never matched.
    assert t.fires_on("SELECT anything") is False


def test_loud_trap_fires_case_insensitively():
    t = Trap(guidance="drop LOWER()", triggers=("LOWER(", "UPPER("))
    assert t.is_loud is True
    assert t.fires_on("select * from x where lower(name) = 'm87'") is True
    assert t.fires_on("SELECT * FROM x WHERE UPPER(name) = 'M87'") is True
    assert t.fires_on("SELECT * FROM x WHERE name = 'M87'") is False


def test_empty_guidance_rejected():
    with pytest.raises(ValueError, match="guidance"):
        Trap(guidance="")


def test_note_trap_is_optional_and_type_checked():
    audit = Audit.manual("n/a")
    assert Note(id="n", text="t", audit=audit).trap is None
    with pytest.raises(TypeError, match="must be a Trap"):
        Note(id="n", text="t", audit=audit, trap="silent")  # type: ignore[arg-type]
