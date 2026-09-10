"""Content assertions for the NRAO Science Data Archive."""

from manna.archives.nrao import ARCHIVE

SCHEMAS = {s.table: s for s in ARCHIVE.schemas}


def test_entry_covers_full_instrument_suite():
    """NRAO's first-party archive serves multiple instruments; the entry
    should reflect that rather than being VLA-only."""
    assert "data.nrao" in ARCHIVE.host_substrings
    assert "data-query.nrao" in ARCHIVE.host_substrings
    for instrument in ("VLA", "VLBA", "GMVA", "GBT"):
        assert instrument in ARCHIVE.description, (
            f"NRAO description must mention {instrument}; got: {ARCHIVE.description}"
        )
    assert ARCHIVE.waveband == "radio"
    assert ARCHIVE.tap_url == "https://data-query.nrao.edu/tap"
    # Non-standard obscore location; pin it so a future contributor doesn't
    # silently "fix" it to ivoa.obscore.
    assert "tap_schema.obscore" in ARCHIVE.notable_tables


def test_usage_notes_capture_critical_gotchas():
    """The usage_notes are the agent-facing knowledge base; NRAO's must cover
    the friction we learned the hard way."""
    notes = " ".join(n.text for n in ARCHIVE.usage_notes).lower()
    assert "async" in notes
    assert "tap_schema.obscore" in notes
    assert "scan" in notes and "execution" in notes.replace("execute", "")
    # Target-name aliasing — Hydra-A -> 3C218 was the live-demo friction.
    assert "3c218" in notes


def test_obscore_schema_missing_columns_and_enums():
    obscore = SCHEMAS["tap_schema.obscore"]
    assert "dataproduct_subtype" in obscore.missing_standard_columns
    # Live 2026-09-10, 0.5° cone on 3C 273 GROUP BY instrument_name, facility_name:
    # EVLA/VLA/VLBA/GBT/GMVA under facility NRAO, plus ALMA rows under facility ALMA.
    # The old enum ({EVLA, VLA, VLBA, GBT}, facility uniformly NRAO) was stale and its
    # count-audit only proved the columns exist — don't let it shrink back.
    assert obscore.value_enums["instrument_name"] == ("EVLA", "VLA", "VLBA", "GBT", "GMVA", "ALMA")
    assert obscore.value_enums["facility_name"] == ("NRAO", "ALMA")
    notes = {n.id: n for n in obscore.notes}
    assert "alma" in notes["instrument-facility-columns"].text.lower()
    # obs_collection is almost always empty (only 'VLASS' and 'RealFast' seen) — the
    # model must select VLASS by project_code, not by collection.
    assert "project_code" in notes["obs-collection-sparse"].text
    # access_format is the literal 'Execution Block', not a MIME type — never branch
    # on it for DataLink the way the ALMA module does.
    assert "Execution Block" in notes["access-format-not-mime"].text


def test_key_note_audits_have_expected_outcomes():
    notes = {n.id: n for n in ARCHIVE.usage_notes}
    assert notes["sync-unfiltered-reads-fail"].audit.expect == "error"
    assert notes["obscore-ivoa-absent"].audit.expect == "empty"


def test_sync_notes_do_not_overstate_async_requirement():
    """Live-probed 2026-07-16 (issue #58): unfiltered obscore reads DO still fail in
    sync, but spatially-filtered reads succeed when NRAO is responsive. So the KB
    must recommend auto/async rather than claim sync is categorically broken —
    otherwise the eval penalises the now-correct mode='auto' behaviour."""
    notes = {n.id: n for n in ARCHIVE.usage_notes}
    routing = notes["async-or-auto-for-data"].text.lower()
    assert "auto" in routing, "the routing note must offer mode='auto', not async-only"

    sync = notes["sync-unfiltered-reads-fail"].text.lower()
    # The observed failure is HTTP 200 + VOTable QUERY_STATUS='ERROR' (or a read
    # timeout), never an actual 5xx — pin the real mechanism so the old, wrong
    # "the /sync endpoint returns 5xx" claim can't creep back in.
    assert "query_status" in sync
    assert "times out" in sync
    assert "filtered" in sync, "the note must distinguish unfiltered from filtered reads"


def test_load_dependent_claims_are_manual_not_probed():
    """A filtered-sync-succeeds probe would report STALE on a transient timeout
    (_verdict maps service_error -> stale for expect='nonempty'), so load-dependent
    claims must stay manual."""
    notes = {n.id: n for n in ARCHIVE.usage_notes}
    assert notes["async-or-auto-for-data"].audit.expect == "manual"


def test_retracted_error_summary_note_stays_gone():
    """`error-summary-empty` claimed NRAO's UWS error_summary is always blank
    (findings N-06). It was our bug: the tools read `job.error_summary`, an
    attribute pyvo's AsyncTAPJob never had, so every archive's message was
    swallowed. NRAO populates errorSummary/message (verified live 2026-09-10:
    "IllegalArgumentException:Function [LOWER] is not found in TapSchema").
    Don't let the note — or its "don't speculate, just simplify" advice — return."""
    ids = {n.id for n in ARCHIVE.usage_notes}
    assert "error-summary-empty" not in ids
    text = " ".join(n.text for n in ARCHIVE.usage_notes).lower()
    assert "error_summary" not in text


def test_lower_upper_note_is_probeable():
    notes = {n.id: n for n in ARCHIVE.usage_notes}
    assert notes["lower-upper-fail"].audit.expect == "error"


def test_string_function_note_covers_concat_and_fires_on_it():
    """Live 2026-09-10: LOWER/UPPER/ILIKE are absent (an OPTIONAL ADQL 2.1 feature
    set, so not a violation — the note must not call it one), and the core-grammar
    string concatenation `||` fails too with a bare JSQLParserException. The loud
    trap should catch `||` as well, since that error text implies no fix."""
    notes = {n.id: n for n in ARCHIVE.usage_notes}
    note = notes["lower-upper-fail"]
    assert "||" in note.text
    assert "spec violation" not in note.text.lower()
    assert note.trap is not None
    assert note.trap.fires_on("SELECT obs_id FROM tap_schema.obscore WHERE target_name || '' = 'x'")
    assert "||" in note.trap.guidance


def test_unfiltered_scans_not_spatial_predicates_are_the_documented_failure():
    """The old `spatial-predicate-required` note said obscore queries without a
    CIRCLE/CONTAINS predicate tend to error even in async. Live 2026-09-10 that
    is false: `instrument_name = 'GBT'` (112 s), `project_code = 'VLASS3.2'`
    (691 s) and an RA/Dec BETWEEN box (278 s) all COMPLETED async with no
    geometry. What fails is the UNFILTERED scan (COUNT(*) → ERROR after ~32 min).
    The note must say that, and must not tell the model geometry is mandatory."""
    ids = {n.id for n in ARCHIVE.usage_notes}
    assert "spatial-predicate-required" not in ids
    notes = {n.id: n for n in ARCHIVE.usage_notes}
    text = notes["unfiltered-scans-fail"].text.lower()
    assert "unfiltered" in text
    assert "non-spatial" in text or "without geometry" in text
    assert "always include" not in text


def test_nrao_count_target():
    from manna.archives._count import ContainsPoint, CountTarget

    ct = ARCHIVE.count_target
    assert isinstance(ct, CountTarget)
    assert ct.table == "tap_schema.obscore"
    assert ct.geometry == ContainsPoint("s_ra", "s_dec")
    assert ct.count_expr == "COUNT(*)"
    assert ct.mode == "async"
