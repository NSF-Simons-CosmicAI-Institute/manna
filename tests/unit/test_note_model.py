import pytest

from manna.archives._audit import Audit
from manna.archives._model import Note, _normalize_notes, note_texts


def test_note_requires_id_text_audit():
    n = Note(
        id="geometry-bbox-ok",
        text="A bounding box works.",
        audit=Audit.probe(expect="ok", adql="SELECT 1"),
    )
    assert n.id and n.text and n.audit.expect == "ok"


def test_note_rejects_empty_id_or_text():
    with pytest.raises(ValueError):
        Note(id="", text="x", audit=Audit.manual("r"))
    with pytest.raises(ValueError):
        Note(id="x", text="", audit=Audit.manual("r"))


def test_note_rejects_non_audit():
    with pytest.raises(TypeError):
        Note(id="x", text="y", audit="not-an-audit")


def test_note_texts_extracts_text_in_order():
    notes = (
        Note(id="a", text="first", audit=Audit.manual("r")),
        Note(id="b", text="second", audit=Audit.manual("r")),
    )
    assert note_texts(notes) == ["first", "second"]


def test_normalize_passes_notes_through():
    n = Note(id="a", text="t", audit=Audit.manual("r"))
    assert _normalize_notes((n,)) == (n,)


def test_normalize_rejects_bare_strings():
    with pytest.raises(TypeError):
        _normalize_notes(("a bare string",))


def test_normalize_rejects_other_types():
    with pytest.raises(TypeError):
        _normalize_notes((123,))
