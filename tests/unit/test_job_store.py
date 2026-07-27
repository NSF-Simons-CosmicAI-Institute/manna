"""JobStore: in-memory keyed handle store for async TAP jobs.

Holds job metadata (URL, ADQL, endpoint) with TTL eviction — never bytes.
"""

import re
import threading
import time
from datetime import UTC, datetime

import pytest

from manna import job_store


@pytest.fixture(autouse=True)
def _clear_jobs():
    # Each test starts with an empty store. Modules are singletons so we
    # must reset between tests.
    with job_store._LOCK:
        job_store._STORE.clear()
    yield
    with job_store._LOCK:
        job_store._STORE.clear()


def test_put_returns_12char_hex_id_and_future_expiry():
    job_id, expires_at = job_store.put(
        job_url="https://example.tap/async/abc",
        endpoint="https://example.tap",
        adql="SELECT 1",
    )
    assert re.fullmatch(r"[0-9a-f]{12}", job_id)
    assert expires_at > datetime.now(UTC)


def test_get_roundtrips_entry_fields():
    job_id, _ = job_store.put(
        job_url="https://example.tap/async/abc",
        endpoint="https://example.tap",
        adql="SELECT TOP 5 * FROM x",
    )
    entry = job_store.get(job_id)
    assert entry is not None
    assert entry.job_url == "https://example.tap/async/abc"
    assert entry.endpoint == "https://example.tap"
    assert entry.adql == "SELECT TOP 5 * FROM x"


def test_get_returns_none_for_unknown_id():
    assert job_store.get("000000000000") is None


def test_evict_removes_entry():
    job_id, _ = job_store.put(
        job_url="u",
        endpoint="e",
        adql="a",
    )
    assert job_store.get(job_id) is not None
    job_store.evict(job_id)
    assert job_store.get(job_id) is None


def test_evict_on_unknown_id_is_a_noop():
    # Should not raise; aborts on already-evicted jobs must be safe.
    job_store.evict("ffffffffffff")


def test_ttl_expiry_drops_entry_on_read():
    job_id, _ = job_store.put(
        job_url="u",
        endpoint="e",
        adql="a",
        ttl_seconds=0.01,
    )
    time.sleep(0.05)
    assert job_store.get(job_id) is None


def test_size_estimate_counts_entries_and_oldest_age():
    job_store.put(job_url="u1", endpoint="e", adql="a")
    time.sleep(0.02)
    job_store.put(job_url="u2", endpoint="e", adql="a")
    stats = job_store.size_estimate()
    assert stats["entries"] == 2
    assert stats["oldest_age_seconds"] >= 0.02


def test_size_estimate_on_empty_store():
    stats = job_store.size_estimate()
    assert stats == {"entries": 0, "oldest_age_seconds": 0}


def test_concurrent_put_get_under_lock():
    # Smoke test — many threads should not corrupt the dict.
    results: list[str] = []

    def worker(i):
        job_id, _ = job_store.put(
            job_url=f"u{i}",
            endpoint="e",
            adql="a",
        )
        results.append(job_id)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(results)) == 50  # all unique
