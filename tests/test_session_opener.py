"""
Tests for the session opener pipeline and API integration.
"""
import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from reflexa.api.deps import get_db, get_llm_client
from reflexa.api.main import create_app
from reflexa.db import crud
from reflexa.db.models import LLMCall, Session as SessionDB
from reflexa.llm.mock import MockLLMClient
from reflexa.pipeline.opener import run_session_opener


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Pipeline-level tests
# ---------------------------------------------------------------------------

async def test_run_session_opener_returns_string(db_session):
    """run_session_opener returns a non-empty string."""
    result = await run_session_opener(
        session_id=str(uuid.uuid4()),
        target_language="es",
        proficiency_level="B1",
        db=db_session,
        llm_client=MockLLMClient(),
    )
    assert isinstance(result, str)
    assert len(result) > 0


async def test_run_session_opener_writes_llm_call_row(db_session):
    """run_session_opener causes exactly one llm_calls row to be written."""
    await run_session_opener(
        session_id=str(uuid.uuid4()),
        target_language="es",
        proficiency_level="B1",
        db=db_session,
        llm_client=MockLLMClient(),
    )
    rows = (await db_session.execute(select(LLMCall))).scalars().all()
    assert len(rows) == 1
    assert rows[0].caller_context == "pipeline/session_opener"


# ---------------------------------------------------------------------------
# API-level tests (HTTPX AsyncClient)
# ---------------------------------------------------------------------------

@pytest.fixture
async def api_client(db_session):
    app = create_app()

    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_llm_client] = lambda: MockLLMClient()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def test_create_session_includes_opener_message(api_client):
    """POST /sessions must return opener_message in the response body."""
    r = await api_client.post(
        "/sessions", json={"target_language": "es", "proficiency_level": "B1"}
    )
    assert r.status_code == 201
    body = r.json()
    assert "opener_message" in body
    assert isinstance(body["opener_message"], str)
    assert body["opener_message"]


async def test_opener_message_stored_in_db(api_client, db_session):
    """After POST /sessions the opener_message is persisted in the sessions table."""
    r = await api_client.post(
        "/sessions", json={"target_language": "es", "proficiency_level": "B1"}
    )
    session_id = r.json()["id"]
    expected_opener = r.json()["opener_message"]

    result = await db_session.execute(
        select(SessionDB).where(SessionDB.id == session_id)
    )
    session = result.scalar_one_or_none()
    assert session is not None
    assert session.opener_message == expected_opener
