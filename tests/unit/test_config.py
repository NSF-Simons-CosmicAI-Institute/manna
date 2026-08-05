from manna.config import Settings


def test_settings_defaults():
    s = Settings(_env_file=None)
    assert s.host == "0.0.0.0"
    assert s.port == 8000
    assert s.log_level == "INFO"


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("MANNA_PORT", "9001")
    s = Settings(_env_file=None)
    assert s.port == 9001


def test_settings_has_tap_sync_timeout_default_20s():
    from manna.config import Settings

    s = Settings()
    assert s.tap_sync_timeout_seconds == 20.0


def test_settings_has_no_job_ttl():
    """Job retention was a JobStore concern; the store is gone, so is the knob."""
    from manna.config import Settings

    assert not hasattr(Settings(), "job_ttl_seconds")


def test_settings_env_override_for_sync_timeout(monkeypatch):
    monkeypatch.setenv("MANNA_TAP_SYNC_TIMEOUT_SECONDS", "5")
    from manna.config import Settings

    s = Settings()
    assert s.tap_sync_timeout_seconds == 5.0
