"""
Phase 1 tests — LLM client and cost estimation.

All tests use the MockLLMClient so no API key is required.
"""
import pytest
from sqlalchemy import select

from reflexa.llm.mock import MockLLMClient
from reflexa.llm.cost import estimate_cost
from reflexa.schemas.feedback import FeedbackOutput, ErrorItem
from reflexa.db.models import LLMCall


# ---------------------------------------------------------------------------
# MockLLMClient.complete() — return value
# ---------------------------------------------------------------------------

async def test_mock_returns_feedback_output(db_session):
    client = MockLLMClient()
    result = await client.complete(
        messages=[{"role": "user", "content": "Yo fui al mercado."}],
        response_model=FeedbackOutput,
        prompt_version_id="baseline/v1",
        caller_context="test/mock",
        db=db_session,
    )
    assert isinstance(result, FeedbackOutput)
    assert result.corrected_utterance
    assert isinstance(result.error_list, list)
    assert all(isinstance(e, ErrorItem) for e in result.error_list)
    assert result.explanations
    assert result.prioritization_and_focus
    assert result.practice_prompt
    assert result.conversation_reply


# ---------------------------------------------------------------------------
# MockLLMClient.complete() — llm_calls row
# ---------------------------------------------------------------------------

async def test_mock_writes_llm_call_row(db_session):
    await MockLLMClient().complete(
        messages=[{"role": "user", "content": "Test"}],
        response_model=FeedbackOutput,
        prompt_version_id="baseline/v1",
        caller_context="test/telemetry",
        db=db_session,
    )
    rows = (await db_session.execute(select(LLMCall))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.model_id == "mock"
    assert row.prompt_version_id == "baseline/v1"
    assert row.caller_context == "test/telemetry"
    assert row.tokens_in == 128
    assert row.tokens_out == 256
    assert row.latency_ms is not None
    assert row.retries == 0
    assert row.error is None


async def test_mock_multiple_calls_write_multiple_rows(db_session):
    client = MockLLMClient()
    for i in range(3):
        await client.complete(
            messages=[{"role": "user", "content": f"msg {i}"}],
            response_model=FeedbackOutput,
            prompt_version_id="baseline/v1",
            caller_context=f"test/call_{i}",
            db=db_session,
        )
    rows = (await db_session.execute(select(LLMCall))).scalars().all()
    assert len(rows) == 3
    contexts = {r.caller_context for r in rows}
    assert contexts == {"test/call_0", "test/call_1", "test/call_2"}


# ---------------------------------------------------------------------------
# MockLLMClient — retry simulation
# ---------------------------------------------------------------------------

async def test_retry_simulation_stores_retry_count(db_session):
    """fail_times=2 should result in retries=2 in the llm_calls row."""
    client = MockLLMClient(fail_times=2)
    result = await client.complete(
        messages=[{"role": "user", "content": "Test retry"}],
        response_model=FeedbackOutput,
        prompt_version_id="baseline/v1",
        caller_context="test/retry",
        db=db_session,
    )
    assert isinstance(result, FeedbackOutput)
    row = (await db_session.execute(select(LLMCall))).scalars().first()
    assert row.retries == 2


async def test_retry_zero_is_default(db_session):
    await MockLLMClient().complete(
        messages=[],
        response_model=FeedbackOutput,
        prompt_version_id="baseline/v1",
        caller_context="test",
        db=db_session,
    )
    row = (await db_session.execute(select(LLMCall))).scalars().first()
    assert row.retries == 0


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------

def test_cost_known_model_gpt4o_mini():
    cost = estimate_cost("gpt-4o-mini", tokens_in=1_000_000, tokens_out=1_000_000)
    assert cost is not None
    # 1M in @ $0.15 + 1M out @ $0.60 = $0.75
    assert abs(cost - 0.75) < 1e-9


def test_cost_known_model_gpt4o():
    cost = estimate_cost("gpt-4o", tokens_in=1_000_000, tokens_out=1_000_000)
    assert cost is not None
    # 1M in @ $2.50 + 1M out @ $10.00 = $12.50
    assert abs(cost - 12.50) < 1e-9


def test_cost_zero_tokens_is_zero():
    cost = estimate_cost("gpt-4o-mini", tokens_in=0, tokens_out=0)
    assert cost == 0.0


def test_cost_unknown_model_returns_none():
    assert estimate_cost("unknown-model-xyz-9999", tokens_in=1000, tokens_out=500) is None


def test_cost_proportional_to_tokens():
    c1 = estimate_cost("gpt-4o-mini", tokens_in=100, tokens_out=50)
    c2 = estimate_cost("gpt-4o-mini", tokens_in=200, tokens_out=100)
    assert c2 is not None and c1 is not None
    assert abs(c2 - 2 * c1) < 1e-12


# ---------------------------------------------------------------------------
# llm_calls row — caller_context and prompt_version_id pass-through
# ---------------------------------------------------------------------------

async def test_llm_call_row_fields_match_arguments(db_session):
    await MockLLMClient().complete(
        messages=[{"role": "user", "content": "Hola"}],
        response_model=FeedbackOutput,
        prompt_version_id="pipeline_draft/v1",
        caller_context="pipeline/corrected/draft",
        db=db_session,
    )
    row = (await db_session.execute(select(LLMCall))).scalars().first()
    assert row.prompt_version_id == "pipeline_draft/v1"
    assert row.caller_context == "pipeline/corrected/draft"
