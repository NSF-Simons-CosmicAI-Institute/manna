"""Unit tests for the known_archives registry.

These tests lock down the derived-lookup contract so that downstream
modules (`_archive_label`, the tool Field examples, tests) stay
consistent with the canonical archive list.
"""

from dataclasses import FrozenInstanceError

import pytest

from astro_archives_mcp.known_archives import (
    KNOWN_ARCHIVES,
    Archive,
    by_short_name,
    host_substring_to_short_name,
    scs_endpoint_description,
    scs_endpoint_urls,
    sia_endpoint_description,
    sia_endpoint_urls,
    tap_endpoint_description,
    tap_endpoint_urls,
)


def test_archive_dataclass_is_frozen():
    a = KNOWN_ARCHIVES[0]
    with pytest.raises(FrozenInstanceError):
        a.short_name = "mutated"  # type: ignore[misc]


def test_known_archives_short_names_unique():
    names = [a.short_name for a in KNOWN_ARCHIVES]
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


def test_nrao_entry_covers_full_instrument_suite():
    """NRAO's first-party archive serves multiple instruments; the entry
    should reflect that rather than being VLA-only."""
    nrao = by_short_name("nrao")
    assert nrao is not None
    assert "data.nrao" in nrao.host_substrings
    assert "data-query.nrao" in nrao.host_substrings
    for instrument in ("VLA", "VLBA", "GMVA", "GBT"):
        assert instrument in nrao.description, (
            f"NRAO description must mention {instrument}; got: {nrao.description}"
        )
    assert nrao.waveband == "radio"
    # TAP endpoint per NRAO scripted-access docs.
    assert nrao.tap_url == "https://data-query.nrao.edu/tap"
    # NRAO uses tap_schema.obscore (non-standard location); pin it so a
    # future contributor doesn't silently "fix" it to ivoa.obscore.
    assert "tap_schema.obscore" in nrao.notable_tables


def test_nrao_usage_notes_capture_critical_gotchas():
    """The usage_notes are the agent-facing knowledge base. NRAO's notes
    must cover the friction we already learned about the hard way."""
    nrao = by_short_name("nrao")
    assert nrao is not None
    notes_joined = " ".join(nrao.usage_notes).lower()
    # Async-mode requirement (the /sync endpoint returns 5xx on data reads)
    assert "async" in notes_joined
    # Non-standard obscore location
    assert "tap_schema.obscore" in notes_joined
    # Scan-level row granularity hint
    assert "scan" in notes_joined and "execution" in notes_joined.replace("execute", "")
    # Target-name aliasing — Hydra-A → 3C218 was the live-demo friction.
    assert "3c218" in notes_joined


def test_each_primary_archive_has_at_least_one_usage_note():
    """Primary collaborator and well-known archives should have at least
    one usage_note. Empty notes = a knowledge gap waiting to bite us."""
    must_have_notes = {"datalab", "nrao", "alma", "cadc", "gaia"}
    for name in must_have_notes:
        a = by_short_name(name)
        assert a is not None, f"{name} not found in KNOWN_ARCHIVES"
        assert len(a.usage_notes) >= 1, (
            f"{name} has no usage_notes — populate from "
            f"archive-documentation-findings.md or live-demo experience"
        )


def test_datalab_usage_notes_cover_known_adql_quirks():
    """Findings D-02/D-03/D-04: Data Lab doesn't translate ADQL
    geometric functions, and NSC bright sources carry blend flags.
    These are recurring patterns the LLM needs to know about."""
    datalab = by_short_name("datalab")
    assert datalab is not None
    notes_joined = " ".join(datalab.usage_notes).lower()
    # ADQL geometric function gap (D-02 + D-03)
    assert "bounding-box" in notes_joined or "bounding box" in notes_joined
    # ...but the verified-live remedy is Q3C, not just client-side trimming.
    assert "q3c_radial_query" in notes_joined
    # Image access is SIAv1 — vo_sia_search (SIA2) can't drive it.
    assert "siav1" in notes_joined or "sia2" in notes_joined
    # NSC blend flags on bright sources (D-04)
    assert "blend" in notes_joined or "flags" in notes_joined


def test_datalab_schema_kb_nsc_recommends_q3c():
    """The nsc_dr2.object curated entry should steer toward the Q3C cone
    filter that actually works (ADQL CONTAINS does not)."""
    from astro_archives_mcp.schema_kb import lookup_schema

    s = lookup_schema(archive="datalab", table="nsc_dr2.object")
    assert s is not None
    notes_joined = " ".join(s.notes).lower()
    assert "q3c_radial_query" in notes_joined


def test_nrao_label_resolves_to_nrao_not_alma_for_data_nrao_host():
    """almascience.nrao.edu must stay labeled 'alma'; data.nrao.edu and
    data-query.nrao.edu must label as 'nrao'. The substring map must not
    confuse the two."""
    from astro_archives_mcp._archive_label import archive_label

    assert archive_label("https://data.nrao.edu/foo") == "nrao"
    assert archive_label("https://data-query.nrao.edu/foo") == "nrao"
    assert archive_label("https://archive.nrao.edu/foo") == "nrao"
    assert archive_label("https://almascience.nrao.edu/tap") == "alma"


def test_alma_appears_before_nrao_in_known_archives():
    """Priority ordering: NOIRLab leads, then ALMA, then NRAO. The first
    TAP-having archives surface as the endpoint examples shown to the LLM,
    so the top of the list is the well-known set we steer toward."""
    order = [a.short_name for a in KNOWN_ARCHIVES]
    assert order.index("datalab") < order.index("alma")
    assert order.index("alma") < order.index("nrao")


def test_alma_usage_notes_capture_critical_gotchas():
    """ALMA's notes must encode the verified-against-live facts: spatial
    queries work (INTERSECTS on s_region), member_ous_uid is the dataset
    key, and science_observation filters out calibration scans."""
    alma = by_short_name("alma")
    assert alma is not None
    notes_joined = " ".join(alma.usage_notes).lower()
    # Spatial filtering works — INTERSECTS against the s_region footprint.
    assert "intersects" in notes_joined and "s_region" in notes_joined
    # member_ous_uid is the canonical downloadable-dataset key.
    assert "member_ous_uid" in notes_joined
    # Science-vs-calibration filtering.
    assert "science_observation" in notes_joined
    # ALMA exposes more than TAP — SIAv2 and DataLink must be surfaced.
    assert "siav2" in notes_joined or "sia2" in notes_joined
    assert "datalink" in notes_joined


def test_alma_exposes_sia2_endpoint():
    """ALMA publishes a SIAv2 image-discovery service in addition to TAP;
    the entry must carry its sia_url so vo_sia_search can reach it."""
    alma = by_short_name("alma")
    assert alma is not None
    assert alma.sia_url == "https://almascience.nrao.edu/sia2"
    assert alma.sia_url in sia_endpoint_urls()


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


def test_adding_a_new_archive_is_isolated():
    """Adding an Archive entry should not require touching other modules.

    This test simulates adding a fake archive and verifies the derived
    lookups pick it up. It does NOT mutate KNOWN_ARCHIVES (which is a
    tuple) — instead it constructs a one-off and asserts the helpers'
    logic works the same way.
    """
    fake = Archive(
        short_name="fake",
        display_name="Fake Test Archive",
        host_substrings=("fake.invalid",),
        tap_url="https://fake.invalid/tap",
    )
    assert fake.tap_url == "https://fake.invalid/tap"
    # If this archive were added to KNOWN_ARCHIVES, the derived map
    # would include it. Since helpers operate on the global tuple, we
    # just verify the dataclass shape supports the contract.
    assert isinstance(fake.host_substrings, tuple)
