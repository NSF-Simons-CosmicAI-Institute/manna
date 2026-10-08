"""_wait_for_phase: the one wait loop behind get_async_job_status and the
run_adql_query async promotion. Driven entirely through the fake clock from
tests/conftest.py — no real sleeping, no HTTP."""

from types import SimpleNamespace

import pytest

from manna import config
from manna.errors import ArchiveError, JobGoneError
from manna.tools import tap as tap_tools

JOB = "https://datalab.noirlab.edu/tap/async/abc"


class _SequenceTap:
    """load_job yields the phases in order and then repeats the last one."""

    def __init__(self, phases):
        self.phases = list(phases)
        self.loads = 0

    def load_job(self, job_url):
        self.loads += 1
        phase = self.phases.pop(0) if len(self.phases) > 1 else self.phases[0]
        return SimpleNamespace(phase=phase)


@pytest.fixture
def seq(monkeypatch):
    def _install(phases):
        tap = _SequenceTap(phases)
        monkeypatch.setattr(tap_tools, "_get_tap", lambda: tap)
        return tap

    return _install


def test_terminal_on_first_read_never_sleeps(seq, wait_clock):
    tap = seq(["COMPLETED"])
    job, phase, waited = tap_tools._wait_for_phase(JOB, budget_s=20)
    assert phase == "COMPLETED"
    assert tap.loads == 1
    assert wait_clock.sleeps == []
    assert waited == 0.0


def test_returns_as_soon_as_job_turns_terminal(seq, wait_clock):
    tap = seq(["EXECUTING", "EXECUTING", "COMPLETED"])
    job, phase, waited = tap_tools._wait_for_phase(JOB, budget_s=20)
    assert phase == "COMPLETED"
    assert tap.loads == 3
    assert wait_clock.sleeps == [2.0, 2.0]
    assert waited == 4.0


def test_budget_exhausted_returns_last_nonterminal_job(seq, wait_clock):
    tap = seq(["EXECUTING"])
    job, phase, waited = tap_tools._wait_for_phase(JOB, budget_s=5)
    assert phase == "EXECUTING"
    # Reads at t=0, 2, 4, 5: the last sleep is trimmed so the budget is never overshot.
    assert wait_clock.sleeps == [2.0, 2.0, 1.0]
    assert tap.loads == 4
    assert waited == 5.0


def test_zero_budget_is_exactly_one_read(seq, wait_clock):
    tap = seq(["EXECUTING"])
    job, phase, waited = tap_tools._wait_for_phase(JOB, budget_s=0)
    assert phase == "EXECUTING"
    assert tap.loads == 1
    assert wait_clock.sleeps == []
    assert waited == 0.0


@pytest.mark.parametrize("phase", ["ERROR", "ABORTED"])
def test_error_and_aborted_are_terminal(seq, wait_clock, phase):
    tap = seq(["EXECUTING", phase])
    job, returned_phase, _ = tap_tools._wait_for_phase(JOB, budget_s=20)
    assert returned_phase == phase
    assert tap.loads == 2


def test_load_job_errors_propagate_unchanged(monkeypatch, wait_clock):
    class _Raises:
        def load_job(self, job_url):
            raise JobGoneError(message="gone")

    monkeypatch.setattr(tap_tools, "_get_tap", lambda: _Raises())
    with pytest.raises(JobGoneError):
        tap_tools._wait_for_phase(JOB, budget_s=20)


def test_load_job_raising_mid_loop_propagates(monkeypatch, wait_clock):
    """A transient read failure after at least one successful non-terminal
    read must propagate to the caller (who is responsible for deciding what
    to do — see _settle_promotion's ArchiveError handling), not be masked."""

    class _RaisesSecondCall:
        def __init__(self):
            self.loads = 0

        def load_job(self, job_url):
            self.loads += 1
            if self.loads == 1:
                return SimpleNamespace(phase="EXECUTING")
            raise ArchiveError(message="read timed out")

    tap = _RaisesSecondCall()
    monkeypatch.setattr(tap_tools, "_get_tap", lambda: tap)
    with pytest.raises(ArchiveError):
        tap_tools._wait_for_phase(JOB, budget_s=20)
    assert wait_clock.sleeps == [2.0]


def test_resolve_wait_budget_default_and_clamp(monkeypatch):
    monkeypatch.setenv("MANNA_ASYNC_WAIT_SECONDS", "20")
    monkeypatch.setenv("MANNA_ASYNC_WAIT_MAX_SECONDS", "30")
    config.get_settings.cache_clear()
    try:
        assert tap_tools._resolve_wait_budget(None) == 20.0
        assert tap_tools._resolve_wait_budget(5) == 5.0
        assert tap_tools._resolve_wait_budget(300) == 30.0
        assert tap_tools._resolve_wait_budget(-3) == 0.0
    finally:
        config.get_settings.cache_clear()
