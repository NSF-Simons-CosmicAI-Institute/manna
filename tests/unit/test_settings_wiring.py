"""Regression tests: MANNA_* settings are actually threaded into runtime.

These two settings were defined on `Settings` and documented in the README
but never wired into the code paths that should consume them — a silent
no-op. These tests lock the wiring in place so it can't regress.
"""

import manna.config as config
from manna import job_store
from manna.tools import tap as tap_tools


def test_get_tap_uses_configured_sync_timeout(monkeypatch):
    """MANNA_TAP_SYNC_TIMEOUT_SECONDS must reach the TapClient that
    _get_tap() constructs, not just live on Settings."""
    monkeypatch.setenv("MANNA_TAP_SYNC_TIMEOUT_SECONDS", "7.5")
    config.get_settings.cache_clear()
    monkeypatch.setattr(tap_tools, "_tap", None)
    try:
        client = tap_tools._get_tap()
        assert client._sync_timeout == 7.5
    finally:
        monkeypatch.setattr(tap_tools, "_tap", None)
        config.get_settings.cache_clear()


def test_promote_async_threads_configured_job_ttl(monkeypatch):
    """MANNA_JOB_TTL_SECONDS must be passed to job_store.put(), so async
    job retention is actually configurable."""
    monkeypatch.setenv("MANNA_JOB_TTL_SECONDS", "120")
    config.get_settings.cache_clear()

    class _FakeTap:
        def submit_async(self, *, endpoint, adql, maxrec):
            return "https://datalab.noirlab.edu/tap/async/abc"

    monkeypatch.setattr(tap_tools, "_get_tap", lambda: _FakeTap())

    captured: dict = {}
    real_put = job_store.put

    def spy_put(**kwargs):
        captured.update(kwargs)
        return real_put(**kwargs)

    monkeypatch.setattr(tap_tools.job_store, "put", spy_put)

    try:
        tap_tools._promote_async(
            endpoint="https://datalab.noirlab.edu/tap",
            adql="SELECT 1",
            maxrec=10,
        )
        assert captured["ttl_seconds"] == 120
    finally:
        config.get_settings.cache_clear()


def test_get_settings_is_cached_singleton():
    """get_settings() returns the same instance until cache_clear()."""
    config.get_settings.cache_clear()
    try:
        assert config.get_settings() is config.get_settings()
    finally:
        config.get_settings.cache_clear()
