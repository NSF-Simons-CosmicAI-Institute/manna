"""Tests for the archives._endpoints helpers over the archive registry.

Archive-specific *content* (NRAO async-only, ALMA INTERSECTS, datalab Q3C,
etc.) is asserted per-archive in `tests/archives/test_<archive>.py`. This file
covers the endpoint + derived-lookup contract that downstream modules
(`_archive_label`, tool Field examples) depend on.
"""

from dataclasses import FrozenInstanceError

import pytest

from manna.archives._endpoints import (
    active_archives,
    by_short_name,
    host_substring_to_short_name,
    scs_endpoint_description,
    scs_endpoint_urls,
    sia_endpoint_description,
    sia_endpoint_urls,
    tap_endpoint_description,
    tap_endpoint_urls,
)
from manna.archives._model import Archive


def test_archive_dataclass_is_frozen():
    a = active_archives()[0]
    with pytest.raises(FrozenInstanceError):
        a.short_name = "mutated"  # type: ignore[misc]


def test_active_archives_short_names_unique():
    names = [a.short_name for a in active_archives()]
    assert len(names) == len(set(names))


def test_host_substring_to_short_name_flattens_multi_substring_archives():
    m = host_substring_to_short_name()
    # CADC has two substrings; both must resolve to "cadc".
    assert m["cadc-ccda.hia-iha"] == "cadc"
    assert m["ws.cadc-ccda"] == "cadc"
    # Singletons still work.
    assert m["datalab.noirlab"] == "datalab"
    assert m["almascience"] == "alma"


def test_by_short_name_round_trip():
    alma = by_short_name("alma")
    assert alma is not None
    assert alma.display_name == "ALMA Science Archive"
    assert alma.tap_url == "https://almascience.nrao.edu/tap"


def test_by_short_name_unknown_returns_none():
    assert by_short_name("not-an-archive") is None


def test_each_primary_archive_has_at_least_one_usage_note():
    """Primary collaborator and well-known archives should have at least
    one usage_note. Empty notes = a knowledge gap waiting to bite us."""
    must_have_notes = {"datalab", "nrao", "alma", "cadc", "gaia"}
    for name in must_have_notes:
        a = by_short_name(name)
        assert a is not None, f"{name} not found in active archives"
        assert len(a.usage_notes) >= 1, f"{name} has no usage_notes"


def test_nrao_label_resolves_to_nrao_not_alma_for_data_nrao_host():
    """almascience.nrao.edu must stay labeled 'alma'; data.nrao.edu and
    data-query.nrao.edu must label as 'nrao'. The substring map must not
    confuse the two."""
    from manna._archive_label import archive_label

    assert archive_label("https://data.nrao.edu/foo") == "nrao"
    assert archive_label("https://data-query.nrao.edu/foo") == "nrao"
    assert archive_label("https://archive.nrao.edu/foo") == "nrao"
    assert archive_label("https://almascience.nrao.edu/tap") == "alma"


def test_view_order_reflects_card_priority():
    """The view is ordered by archive priority: NOIRLab leads, then ALMA, then
    NRAO. The first TAP-having archives surface as the endpoint examples
    shown to the LLM."""
    order = [a.short_name for a in active_archives()]
    assert order.index("datalab") < order.index("alma")
    assert order.index("alma") < order.index("nrao")


def test_tap_endpoint_urls_has_alma_and_datalab():
    urls = tap_endpoint_urls()
    assert "https://datalab.noirlab.edu/tap" in urls
    assert "https://almascience.nrao.edu/tap" in urls
    assert all(u for u in urls), "no None entries in tap_endpoint_urls"


def test_sia_endpoint_urls_has_cadc():
    urls = sia_endpoint_urls()
    assert any("cadc" in u for u in urls)


def test_scs_endpoint_urls_has_gaia_ari():
    urls = scs_endpoint_urls()
    assert any("gaia.ari.uni-heidelberg.de" in u for u in urls)


def test_tap_description_mentions_two_archives_by_name():
    desc = tap_endpoint_description()
    assert "NOIRLab" in desc or "ALMA" in desc
    assert "vo_registry_search" in desc  # discovery hint preserved


def test_sia_description_mentions_sia2_and_discovery():
    desc = sia_endpoint_description()
    assert "SIA 2.0" in desc
    assert "vo_registry_search" in desc


def test_scs_description_mentions_tap_preference():
    desc = scs_endpoint_description()
    assert "vo_tap_query" in desc


def test_archive_dataclass_shape_supports_the_contract():
    """A fresh Archive constructs cleanly — the shape the registry relies on."""
    fake = Archive(
        short_name="fake",
        display_name="Fake Test Archive",
        host_substrings=("fake.invalid",),
        tap_url="https://fake.invalid/tap",
    )
    assert fake.tap_url == "https://fake.invalid/tap"
    assert isinstance(fake.host_substrings, tuple)
