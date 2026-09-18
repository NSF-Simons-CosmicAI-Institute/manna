"""docs/contributing/adding-an-archive.md must name every archive-model field.

The page promises a field-by-field reference. This introspects the dataclasses
so a field added to the model without a row in the page fails here, offline.
"""

import dataclasses
from pathlib import Path

import pytest

from manna.archives._audit import Audit
from manna.archives._count import ContainsPoint, CountTarget, IntersectsRegion, Q3CRadial
from manna.archives._model import Archive, Note, Pitfall, Schema

PAGE = Path(__file__).resolve().parents[2] / "docs" / "contributing" / "adding-an-archive.md"

MODEL_CLASSES = [Archive, Note, Audit, Pitfall, Schema, CountTarget]
GEOMETRY_CLASSES = [Q3CRadial, ContainsPoint, IntersectsRegion]
AUDIT_CONSTRUCTORS = ["Audit.probe", "Audit.count", "Audit.manual"]


@pytest.fixture(scope="module")
def page_text() -> str:
    assert PAGE.exists(), f"{PAGE} is missing"
    return PAGE.read_text()


@pytest.mark.parametrize("cls", MODEL_CLASSES, ids=lambda c: c.__name__)
def test_every_field_is_named_in_the_page(page_text: str, cls: type) -> None:
    for f in dataclasses.fields(cls):
        assert f"`{f.name}`" in page_text, f"{cls.__name__}.{f.name} has no row in the page"


@pytest.mark.parametrize("cls", GEOMETRY_CLASSES, ids=lambda c: c.__name__)
def test_every_geometry_class_is_named(page_text: str, cls: type) -> None:
    assert f"`{cls.__name__}`" in page_text


@pytest.mark.parametrize("ctor", AUDIT_CONSTRUCTORS)
def test_every_audit_constructor_is_named(page_text: str, ctor: str) -> None:
    assert f"`{ctor}`" in page_text
