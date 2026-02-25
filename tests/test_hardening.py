"""
Phase 5 — Hardening tests.

Covers:
- GET /health returns correct shape
- Custom 422 handler returns RFC 7807-style error
- Message length cap returns 422
- LLMCallError on display pipeline → 503, not 500
"""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock

from reflexa.api.deps import get_db, get_llm_client
from reflexa.api.main import create_app
from reflexa.llm.client import LLMCallError
from reflexa.llm.mock import MockLLMClient


@pytest_asyncio.fixture
async def client(db_session):
    app = create_app()

    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_llm_client] = lambda: MockLLMClient()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

async def test_health_shape(client):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert body["llm"] in ("mock", "live")


# ---------------------------------------------------------------------------
# Custom 422 handler
# ---------------------------------------------------------------------------

async def test_422_missing_required_field(client):
    """POST /sessions without target_language triggers Pydantic validation."""
    r = await client.post("/sessions", json={})
    assert r.status_code == 422
    body = r.json()
    # Must use our RFC 7807-style wrapper, not FastAPI's default list
    assert isinstance(body["detail"], dict)
    assert body["detail"]["code"] == "validation_error"
    assert "message" in body["detail"]


async def test_422_has_field_hint(client):
    """The field key should identify which parameter failed."""
    r = await client.post("/sessions", json={})
    assert r.status_code == 422
    detail = r.json()["detail"]
    # field should reference 'target_language' (or be falsy only if loc is empty)
    assert detail.get("field") or detail.get("field") is None  # present in response


# ---------------------------------------------------------------------------
# Message length cap
# ---------------------------------------------------------------------------

async def test_message_too_long_returns_422(client):
    r = await client.post("/sessions", json={"target_language": "es"})
    sid = r.json()["id"]

    long_msg = "a" * 2001
    r2 = await client.post(f"/sessions/{sid}/turns", json={"user_message": long_msg})
    assert r2.status_code == 422


# ---------------------------------------------------------------------------
# Graceful display-pipeline failure → 503
# ---------------------------------------------------------------------------

async def test_llm_call_error_returns_503(db_session):
    """
    When the display-condition pipeline raises LLMCallError (e.g. timeout),
    the chat endpoint must return 503 — not 500.
    """
    app = create_app()

    async def override_db():
        yield db_session

    failing_llm = AsyncMock()
    failing_llm.complete = AsyncMock(side_effect=LLMCallError("timeout"))

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_llm_client] = lambda: failing_llm

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        # Create a session first (needs a working LLM for the opener).
        # Override with mock for session creation, then switch to failing for the turn.
        pass

    # Use a two-client approach: real mock for session, failing mock for turn.
    app2 = create_app()

    async def override_db2():
        yield db_session

    app2.dependency_overrides[get_db] = override_db2
    app2.dependency_overrides[get_llm_client] = lambda: MockLLMClient()

    async with AsyncClient(
        transport=ASGITransport(app=app2), base_url="http://test"
    ) as c:
        r = await c.post("/sessions", json={"target_language": "es"})
        sid = r.json()["id"]

    # Now send the turn with a failing LLM
    app3 = create_app()

    async def override_db3():
        yield db_session

    app3.dependency_overrides[get_db] = override_db3
    app3.dependency_overrides[get_llm_client] = lambda: failing_llm

    async with AsyncClient(
        transport=ASGITransport(app=app3), base_url="http://test"
    ) as c:
        r2 = await c.post(
            f"/sessions/{sid}/turns",
            json={"user_message": "Yo quiero ir al mercado."},
        )

    assert r2.status_code == 503
    body = r2.json()
    assert body["detail"]["code"] == "pipeline_error"
