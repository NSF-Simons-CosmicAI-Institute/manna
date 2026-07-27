# tests/archives/test_audits.py
"""The audit coverage gate: every atomic note is addressable and well-formed.

'Every note has an audit' is a construction invariant (Note requires an Audit),
so this only guards uniqueness, addressability, and reports the manual surface.
"""

from manna.archives import get_active_archives
from manna.archives._audit import AUDIT_EXPECTS


def _all_notes():
    """(archive_short_name, note) for every usage_note and schema note, active set."""
    for a in get_active_archives():
        for n in a.usage_notes:
            yield a.short_name, n
        for s in a.schemas:
            for n in s.notes:
                yield a.short_name, n


def test_note_ids_unique_within_each_archive():
    seen: dict[str, set[str]] = {}
    for archive, note in _all_notes():
        ids = seen.setdefault(archive, set())
        assert note.id not in ids, f"duplicate note id {archive}:{note.id}"
        ids.add(note.id)


def test_every_audit_is_well_formed():
    for archive, note in _all_notes():
        a = note.audit
        assert a.expect in AUDIT_EXPECTS, f"{archive}:{note.id} bad expect {a.expect!r}"
        if a.expect == "manual":
            assert a.reason, f"{archive}:{note.id} manual audit needs a reason"
        elif a.expect == "count":
            assert a.columns and a.adql, f"{archive}:{note.id} count audit malformed"
        else:
            assert a.adql, f"{archive}:{note.id} probe audit needs adql"


def test_report_probeable_vs_manual(capsys):
    """Not an assertion — prints the manual surface so a rise in un-verifiable
    notes is visible in one place when running -s."""
    counts: dict[str, list[int]] = {}
    for archive, note in _all_notes():
        p, m = counts.setdefault(archive, [0, 0])
        if note.audit.expect == "manual":
            counts[archive][1] += 1
        else:
            counts[archive][0] += 1
    for archive, (probeable, manual) in sorted(counts.items()):
        print(f"{archive}: {probeable} probeable, {manual} manual")
    assert counts  # at least one archive has notes
