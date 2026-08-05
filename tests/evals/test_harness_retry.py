"""The transient-error retry around model.complete.

A shared vLLM endpoint throws connection blips under load; without a retry those
silently fail whichever ablation arm runs during a flaky window (observed: one arm
at 0% infra-fail, the other at 39%), biasing the comparison. Pin the retry so a
transient error is recovered but a persistent one still surfaces.
"""

from __future__ import annotations

import pytest

from evals.harness import _complete_with_retry, _is_transient


class _ConnErr(Exception):
    """Stands in for anthropic.APIConnectionError without importing the SDK type."""

    def __init__(self):
        super().__init__("Connection error.")

    @property
    def __class__(self):  # make type(exc).__name__ read as the SDK class name
        return _APIConnectionError


class _APIConnectionError(Exception):
    pass


class _FlakyModel:
    """Fails `fail_n` times with a transient error, then returns a sentinel."""

    def __init__(self, fail_n: int, exc: Exception | None = None):
        self.fail_n = fail_n
        self.calls = 0
        self._exc = exc or _APIConnectionError("APIConnectionError: Connection error.")

    async def complete(self, system, convo, tools):
        self.calls += 1
        if self.calls <= self.fail_n:
            raise self._exc
        return "OK"


def test_is_transient_recognizes_connection_and_timeout():
    assert _is_transient(_APIConnectionError("APIConnectionError: Connection error."))
    assert _is_transient(RuntimeError("Request timed out or interrupted"))
    assert not _is_transient(ValueError("bad ADQL syntax"))


async def test_retry_recovers_from_transient_then_succeeds(monkeypatch):
    import evals.harness as h

    monkeypatch.setattr(h.asyncio, "sleep", lambda *_a, **_k: _noop())
    model = _FlakyModel(fail_n=2)
    out = await _complete_with_retry(model, "sys", [], [], attempts=3, backoff=0.0)
    assert out == "OK"
    assert model.calls == 3  # two failures + one success


async def test_retry_reraises_after_exhausting_attempts(monkeypatch):
    import evals.harness as h

    monkeypatch.setattr(h.asyncio, "sleep", lambda *_a, **_k: _noop())
    model = _FlakyModel(fail_n=5)
    with pytest.raises(_APIConnectionError):
        await _complete_with_retry(model, "sys", [], [], attempts=3, backoff=0.0)
    assert model.calls == 3


async def test_non_transient_error_is_not_retried():
    class _Boom:
        calls = 0

        async def complete(self, *a):
            self.calls += 1
            raise ValueError("bad ADQL")

    m = _Boom()
    with pytest.raises(ValueError):
        await _complete_with_retry(m, "sys", [], [], attempts=3, backoff=0.0)
    assert m.calls == 1  # not retried


async def _noop():
    return None
