"""In-memory keyed JobStore for async TAP job handles.

Stores enough state to re-hydrate an UWS job (job_url, plus
debug-friendly metadata) and serve /health stats. Process lifetime;
lost on restart. Single-instance (no cross-worker sharing — fine for
the single-process deployment).

Eviction is check-on-read: when `get` finds an expired entry, it deletes
it before returning None. No background sweeper.

The JobStore is a directory, not a cache: it does NOT hold result bytes
or the live phase. Result bytes never touch the server — the client
fetches them from the archive via the job_url; the phase is always
live-fetched from the upstream UWS.
"""

import threading
import uuid as _uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

_DEFAULT_TTL_SECONDS = 3600  # 1 hour — async jobs themselves run for minutes.


@dataclass(frozen=True)
class JobEntry:
    job_url: str
    endpoint: str
    adql: str
    created_at: datetime
    expires_at: datetime


_STORE: dict[str, JobEntry] = {}
_LOCK = threading.RLock()


def put(
    *,
    job_url: str,
    endpoint: str,
    adql: str,
    ttl_seconds: float = _DEFAULT_TTL_SECONDS,
) -> tuple[str, datetime]:
    """Store a job handle. Returns (job_id_hex, expires_at).

    job_id_hex is a 12-character random uuid4 prefix — short enough to
    log readably, long enough that collisions are vanishingly rare
    within a process lifetime.
    """
    job_id = _uuid.uuid4().hex[:12]
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=ttl_seconds)
    entry = JobEntry(
        job_url=job_url,
        endpoint=endpoint,
        adql=adql,
        created_at=now,
        expires_at=expires_at,
    )
    with _LOCK:
        _STORE[job_id] = entry
    return job_id, expires_at


def get(job_id: str) -> JobEntry | None:
    """Return the entry if present and not expired. Evicts expired entries."""
    with _LOCK:
        entry = _STORE.get(job_id)
        if entry is None:
            return None
        if datetime.now(UTC) >= entry.expires_at:
            del _STORE[job_id]
            return None
        return entry


def evict(job_id: str) -> None:
    """Remove a job entry. No-op if not present."""
    with _LOCK:
        _STORE.pop(job_id, None)


def size_estimate() -> dict[str, int | float]:
    """Surfaced on /health for ops visibility.

    Returns entries (count) and oldest_age_seconds (float). bytes are not
    tracked here — job entries are tiny; entry count + age is the useful
    operator signal. Count includes not-yet-evicted expired entries
    (eviction is check-on-read).
    """
    with _LOCK:
        entries = len(_STORE)
        if entries == 0:
            return {"entries": 0, "oldest_age_seconds": 0.0}
        now = datetime.now(UTC)
        oldest = min(e.created_at for e in _STORE.values())
        return {
            "entries": entries,
            "oldest_age_seconds": (now - oldest).total_seconds(),
        }
