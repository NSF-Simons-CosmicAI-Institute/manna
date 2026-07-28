"""/health surfaces job_store metrics for ops visibility."""

import pytest
from httpx import ASGITransport, AsyncClient

from manna import job_store
from manna.app import build_app


@pytest.fixture(autouse=True)
def _clear_jobs():
    with job_store._LOCK:
        job_store._STORE.clear()
    yield
    with job_store._LOCK:
        job_store._STORE.clear()


@pytest.mark.asyncio
async def test_health_reports_empty_job_store():
    app = build_app()
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            body = resp.json()
            assert "job_store" in body
            assert body["job_store"] == {"entries": 0, "oldest_age_seconds": 0.0}


@pytest.mark.asyncio
async def test_health_reports_active_job_store():
    job_store.put(
        job_url="https://example.tap/async/abc",
        endpoint="https://example.tap",
        adql="SELECT 1",
    )
    app = build_app()
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/health")
            body = resp.json()
            assert body["job_store"]["entries"] == 1
            assert body["job_store"]["oldest_age_seconds"] >= 0
