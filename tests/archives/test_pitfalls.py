"""Pitfall derivation over the active archive set (issue #57).

The cheatsheet is DERIVED from tagged notes, not hardcoded — the thing this
replaces was a hand-written cheatsheet constant in `evals/harness.py`, an experiment artifact
whose own comment said a real version would derive it from tagged notes.
"""

import pytest

from manna.archives import get_active_archives
from manna.archives._pitfalls import (
    CHEATSHEET_TOKEN_BUDGET,
    error_hint_for,
    estimate_tokens,
    pitfall_notes,
    upfront_note_cheatsheet,
)
from manna.config import get_settings


@pytest.fixture
def clear_archive_caches():
    """Reset the settings + active-archive caches around a test that toggles env."""
    get_settings.cache_clear()
    get_active_archives.cache_clear()
    yield
    get_settings.cache_clear()
    get_active_archives.cache_clear()


# ---------- up-front notes -> vo_tap_query description ----------


def test_cheatsheet_covers_the_tagged_silent_pitfalls():
    cs = upfront_note_cheatsheet()
    # ALMA granularity: the archetypal up-front note (COUNT(*) over-counts, no error).
    assert "COUNT(DISTINCT member_ous_uid)" in cs
    # Data Lab geometry: errors, but unactionably.
    assert "q3c_radial_query" in cs
    # NRAO's non-standard obscore location.
    assert "tap_schema.obscore" in cs


def test_cheatsheet_stays_within_the_token_budget():
    """The description is re-sent every turn, so this blob is recurring rent.
    If a new pitfall blows the ceiling, write terser guidance — don't raise it."""
    assert estimate_tokens(upfront_note_cheatsheet()) <= CHEATSHEET_TOKEN_BUDGET


def test_cheatsheet_keys_each_line_to_the_tap_host():
    """The model joins on the `endpoint` it passes to vo_tap_query. NRAO's
    host_substrings[0] is 'data.nrao', which never appears in its TAP endpoint
    'data-query.nrao.edu' — keying on that would point at the wrong archive."""
    lines = {line.split(" (")[0]: line for line in upfront_note_cheatsheet().splitlines()[1:]}
    nrao = next(v for k, v in lines.items() if "NRAO" in k)
    assert "data-query.nrao" in nrao


def test_cheatsheet_excludes_the_error_hint_pitfall():
    """LOWER/UPPER throws and now ships a hint, so it must not spend description
    budget — this is exactly the split the exp_a harness comment called for."""
    assert "LOWER(" not in upfront_note_cheatsheet()


def test_cheatsheet_honours_stable_archives_selection(monkeypatch, clear_archive_caches):
    monkeypatch.setenv("MANNA_ARCHIVES", "alma")
    get_settings.cache_clear()
    get_active_archives.cache_clear()
    cs = upfront_note_cheatsheet()
    assert "COUNT(DISTINCT member_ous_uid)" in cs  # alma is active
    assert "q3c_radial_query" not in cs  # datalab is not
    assert "tap_schema.obscore" not in cs  # nrao is not


def test_cheatsheet_empty_when_no_active_archive_tags_a_pitfall(monkeypatch, clear_archive_caches):
    """An empty blob must leave the description untouched rather than append a
    bare header — a selection with no tagged pitfalls is legitimate."""
    monkeypatch.setenv("MANNA_ARCHIVES", "sdss")
    get_settings.cache_clear()
    get_active_archives.cache_clear()
    assert upfront_note_cheatsheet() == ""


# ---------- error hints -> error payload `hint` ----------


@pytest.mark.parametrize(
    "adql",
    [
        "SELECT TOP 10 * FROM tap_schema.obscore WHERE LOWER(target_name) = 'm87'",
        "SELECT TOP 10 * FROM tap_schema.obscore WHERE lower(target_name) LIKE '%m87%'",
        "SELECT TOP 10 * FROM tap_schema.obscore WHERE UPPER(target_name) = 'M87'",
    ],
)
def test_error_hint_matches_nrao_lower_upper(adql):
    guidance = error_hint_for("nrao", adql)
    assert guidance is not None
    assert "LOWER()" in guidance


def test_error_hint_absent_on_clean_adql_and_other_archives():
    clean = "SELECT TOP 10 * FROM tap_schema.obscore WHERE target_name = '3C274'"
    assert error_hint_for("nrao", clean) is None
    # LOWER() is fine at Data Lab — the pitfall is NRAO's, not a global rule.
    assert error_hint_for("datalab", "SELECT LOWER(x) FROM y") is None
    # An archive we make no claims about must not gain a hint from nowhere.
    assert error_hint_for("nonesuch", "SELECT LOWER(x) FROM y") is None


def test_pitfall_notes_partitions_by_channel():
    nrao = next(a for a in get_active_archives() if a.short_name == "nrao")
    assert [n.id for n in pitfall_notes(nrao, channel="error_hint")] == ["lower-upper-fail"]
    assert "lower-upper-fail" not in [n.id for n in pitfall_notes(nrao, channel="upfront")]
