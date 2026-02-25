"""
Phase 2 — API integration tests via HTTPX AsyncClient.
"""
import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from reflexa.api.deps import get_db, get_llm_client
from reflexa.api.main import create_app
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
# Health
# ---------------------------------------------------------------------------

async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["llm"] in ("mock", "live")


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

async def test_create_session(client):
    r = await client.post("/sessions", json={"target_language": "es", "proficiency_level": "B1"})
    assert r.status_code == 201
    body = r.json()
    assert body["target_language"] == "es"
    assert body["proficiency_level"] == "B1"
    assert "id" in body
    assert "created_at" in body
    assert "opener_message" in body
    assert body["opener_message"]  # non-empty string from mock


async def test_get_session(client):
    r = await client.post("/sessions", json={"target_language": "fr"})
    session_id = r.json()["id"]

    r2 = await client.get(f"/sessions/{session_id}")
    assert r2.status_code == 200
    body = r2.json()
    assert body["id"] == session_id
    assert body["turn_count"] == 0


async def test_get_session_not_found(client):
    r = await client.get("/sessions/does-not-exist")
    assert r.status_code == 404


async def test_get_session_history_empty(client):
    r = await client.post("/sessions", json={"target_language": "es"})
    sid = r.json()["id"]
    r2 = await client.get(f"/sessions/{sid}/history")
    assert r2.status_code == 200
    assert r2.json()["turns"] == []


# ---------------------------------------------------------------------------
# Turns
# ---------------------------------------------------------------------------

async def test_create_turn_returns_feedback(client):
    r = await client.post("/sessions", json={"target_language": "es", "proficiency_level": "B1"})
    sid = r.json()["id"]

    r2 = await client.post(
        f"/sessions/{sid}/turns",
        json={"user_message": "Yo fui al mercado ayer y compré vegetables."},
    )
    assert r2.status_code == 201
    body = r2.json()
    assert body["turn_id"]
    assert body["turn_index"] == 0

    fb = body["feedback"]
    assert fb["corrected_utterance"]
    assert isinstance(fb["error_list"], list)
    assert fb["explanations"]
    assert fb["prioritization_and_focus"]
    assert fb["practice_prompt"]
    assert fb["conversation_reply"]
    assert fb["pipeline_run_id"]
    assert isinstance(fb["latency_ms"], int)


async def test_create_turn_increments_index(client):
    r = await client.post("/sessions", json={"target_language": "es"})
    sid = r.json()["id"]

    r1 = await client.post(f"/sessions/{sid}/turns", json={"user_message": "Hola"})
    r2 = await client.post(f"/sessions/{sid}/turns", json={"user_message": "Adiós"})

    assert r1.json()["turn_index"] == 0
    assert r2.json()["turn_index"] == 1


async def test_create_turn_session_not_found(client):
    r = await client.post(
        "/sessions/no-such-session/turns",
        json={"user_message": "Test"},
    )
    assert r.status_code == 404


async def test_session_turn_count_increases(client):
    r = await client.post("/sessions", json={"target_language": "es"})
    sid = r.json()["id"]

    await client.post(f"/sessions/{sid}/turns", json={"user_message": "Uno"})
    await client.post(f"/sessions/{sid}/turns", json={"user_message": "Dos"})

    r2 = await client.get(f"/sessions/{sid}")
    assert r2.json()["turn_count"] == 2


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------

async def test_get_turn_artifacts_after_both_pipelines(client, db_session):
    """
    Both conditions run for every turn; after a small delay the background
    task (alternate pipeline) will have completed.  We explicitly run both
    via the direct pipeline API in test_pipeline.py; here we just verify
    the baseline (display) artifacts exist immediately.
    """
    r = await client.post("/sessions", json={"target_language": "es"})
    sid = r.json()["id"]
    turn_resp = await client.post(
        f"/sessions/{sid}/turns",
        json={"user_message": "Yo quiero ir a la tienda."},
    )
    tid = turn_resp.json()["turn_id"]

    # Wait for the background alternate-condition task to finish
    await asyncio.sleep(0.3)

    r2 = await client.get(f"/turns/{tid}/artifacts")
    assert r2.status_code == 200
    body = r2.json()
    assert body["turn_id"] == tid
    # At minimum the display-condition artifact exists
    assert len(body["artifacts"]) >= 1
    stages = {a["stage"] for a in body["artifacts"]}
    assert "baseline" in stages


async def test_get_turn_feedback_condition(client):
    r = await client.post("/sessions", json={"target_language": "es"})
    sid = r.json()["id"]
    turn_resp = await client.post(
        f"/sessions/{sid}/turns",
        json={"user_message": "Tengo hambre."},
    )
    tid = turn_resp.json()["turn_id"]

    r2 = await client.get(f"/turns/{tid}/feedback/baseline")
    assert r2.status_code == 200
    body = r2.json()
    assert body["condition"] == "baseline"
    assert body["corrected_utterance"]


async def test_get_turn_feedback_invalid_condition(client):
    r = await client.post("/sessions", json={"target_language": "es"})
    sid = r.json()["id"]
    turn_resp = await client.post(
        f"/sessions/{sid}/turns",
        json={"user_message": "Test"},
    )
    tid = turn_resp.json()["turn_id"]

    r2 = await client.get(f"/turns/{tid}/feedback/invalid")
    assert r2.status_code == 400
