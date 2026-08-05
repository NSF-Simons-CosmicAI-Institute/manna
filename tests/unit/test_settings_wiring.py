"""Regression tests: MANNA_* settings are actually threaded into runtime.

These settings were defined on `Settings` and documented in the README but
never wired into the code paths that should consume them — a silent no-op.
These tests lock the wiring in place so it can't regress.

MANNA_ALLOWED_HOSTS has equivalent coverage in tests/unit/test_url_guard.py,
which drives it through the environment rather than stubbing Settings.
"""

import manna.config as config
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


def test_promote_async_records_no_server_side_state(monkeypatch):
    """Replaces the old MANNA_JOB_TTL_SECONDS wiring test.

    Job retention used to be a server concern (a TTL on the JobStore entry).
    There is no store now, so the setting is gone and the invariant worth
    pinning is the opposite one: promoting to async returns the upstream handle
    and leaves nothing behind in this process.
    """

    class _FakeTap:
        def submit_async(self, *, endpoint, adql, maxrec):
            return "https://datalab.noirlab.edu/tap/async/abc"

    monkeypatch.setattr(tap_tools, "_get_tap", lambda: _FakeTap())

    payload = tap_tools._promote_async(
        endpoint="https://datalab.noirlab.edu/tap",
        adql="SELECT 1",
        maxrec=10,
    )

    assert payload["job_url"] == "https://datalab.noirlab.edu/tap/async/abc"
    assert "job_id" not in payload
    assert not hasattr(config.Settings(), "job_ttl_seconds")


def test_get_settings_is_cached_singleton():
    """get_settings() returns the same instance until cache_clear()."""
    config.get_settings.cache_clear()
    try:
        assert config.get_settings() is config.get_settings()
    finally:
        config.get_settings.cache_clear()
