"""Offline unit tests for the derived audit runner (evals/audit.py).

No network: the live probe (`_probe`) is monkeypatched, so these exercise the verdict
routing — including the STALE-vs-UNREACHABLE hardening — deterministically.
"""

from __future__ import annotations

import pytest

from astro_archives_mcp.archives._audit import Audit
from astro_archives_mcp.archives._model import Note
from evals import audit
from evals.audit import _verdict, check_note


# --------------------------------------------------------------------------- #
# _verdict — the ok/error/empty/nonempty routing + service-error handling
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "expect,outcome,n_rows,want",
    [
        ("ok", "ok", 1, "still_true"),
        ("ok", "query_error", 0, "stale"),
        ("ok", "service_error", 0, "unreachable"),
        ("error", "query_error", 0, "still_true"),
        ("error", "service_error", 0, "still_true"),
        ("error", "ok", 1, "stale"),
        ("empty", "ok", 0, "still_true"),
        ("empty", "ok", 3, "stale"),
        ("nonempty", "ok", 2, "still_true"),
        ("nonempty", "ok", 0, "stale"),
    ],
)
def test_verdict_routing(expect, outcome, n_rows, want):
    assert _verdict(expect, outcome, n_rows) == want


class _StubArchive:
    short_name = "datalab"
    tap_url = "https://example/tap"


def test_manual_note_never_probes():
    n = Note(id="x", text="t", audit=Audit.manual("verify by hand"))
    row = check_note(_StubArchive(), n, control_ok=True)
    assert row["status"] == "manual"


def test_control_failed_is_unreachable(monkeypatch):
    n = Note(id="x", text="t", audit=Audit.probe(expect="ok", adql="SELECT 1"))
    row = check_note(_StubArchive(), n, control_ok=False)
    assert row["status"] == "unreachable"


def test_count_missing_column_is_stale_and_named(monkeypatch):
    monkeypatch.setattr(audit, "_probe", lambda *a, **k: ("ok", 1, ["instrument_name"], ""))
    n = Note(
        id="instr",
        text="instrument_name + facility_name exist",
        audit=Audit.count(table="tap_schema.obscore", columns=("instrument_name", "facility_name")),
    )
    row = check_note(_StubArchive(), n, control_ok=True)
    assert row["status"] == "stale"
    assert "facility_name" in row["detail"]


# --------------------------------------------------------------------------- #
# endpoint_dead — a hard 404 endpoint is a stale-KB signal, not a blip
# --------------------------------------------------------------------------- #
def test_control_state_dead_on_404(monkeypatch):
    monkeypatch.setattr(
        audit,
        "_probe",
        lambda client, endpoint, adql, retries=1: (
            "service_error",
            0,
            [],
            "ArchiveError: 404 Client Error: Not Found for url: https://x/tap/sync",
        ),
    )
    assert audit._control_state("https://x/tap", audit._CONTROL_ADQL) == "dead"


def test_control_state_down_on_timeout(monkeypatch):
    monkeypatch.setattr(
        audit,
        "_probe",
        lambda client, endpoint, adql, retries=1: ("service_error", 0, [], "ReadTimeout"),
    )
    assert audit._control_state("https://x/tap", audit._CONTROL_ADQL) == "down"


def test_check_note_reports_endpoint_dead(monkeypatch):
    from astro_archives_mcp.archives._model import Archive

    arch = Archive(
        short_name="x",
        display_name="X",
        host_substrings=("x.example",),
        tap_url="https://x.example/tap",
        usage_notes=(Note(id="n1", text="claim", audit=Audit.probe(expect="ok", adql="SELECT 1")),),
    )
    row = check_note(arch, arch.usage_notes[0], control_ok=False, control_dead=True)
    assert row["status"] == "endpoint_dead"
