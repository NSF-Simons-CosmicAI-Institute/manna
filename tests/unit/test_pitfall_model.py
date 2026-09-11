"""The Pitfall model — the declarative half of pitfall delivery (issue #57).

The channel is carried entirely by `triggers`: none ⇒ up-front note (preventive,
always shown; `channel == "upfront"`), some ⇒ error hint (reactive, fires on a
matching ADQL; `channel == "error_hint"`).
"""

import pytest

from manna.archives._audit import Audit
from manna.archives._model import Note, Pitfall


def test_triggerless_pitfall_is_upfront_and_never_fires():
    t = Pitfall(guidance="use q3c_radial_query")
    assert t.channel == "upfront"
    # An up-front note is preventive — it is always shown, never matched.
    assert t.fires_on("SELECT anything") is False


def test_error_hint_pitfall_fires_case_insensitively():
    t = Pitfall(guidance="drop LOWER()", triggers=("LOWER(", "UPPER("))
    assert t.channel == "error_hint"
    assert t.fires_on("select * from x where lower(name) = 'm87'") is True
    assert t.fires_on("SELECT * FROM x WHERE UPPER(name) = 'M87'") is True
    assert t.fires_on("SELECT * FROM x WHERE name = 'M87'") is False


def test_empty_guidance_rejected():
    with pytest.raises(ValueError, match="guidance"):
        Pitfall(guidance="")


def test_note_pitfall_is_optional_and_type_checked():
    audit = Audit.manual("n/a")
    assert Note(id="n", text="t", audit=audit).pitfall is None
    with pytest.raises(TypeError, match="must be a Pitfall"):
        Note(id="n", text="t", audit=audit, pitfall="silent")  # type: ignore[arg-type]
