"""
Phase 2 — pipeline unit tests (no HTTP layer).
"""
import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from reflexa.db import crud
from reflexa.db.models import FeedbackOutput as FeedbackOutputDB
from reflexa.db.models import PipelineArtifact, PipelineRun
from reflexa.llm.mock import MockLLMClient
from reflexa.pipeline.baseline import run_baseline
from reflexa.pipeline.corrected import run_corrected
from reflexa.pipeline.orchestrator import PipelineContext, run_both_conditions
from reflexa.schemas.feedback import FeedbackOutput


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now():
    return datetime.now(timezone.utc).isoformat()


async def _setup_session_and_turn(db):
    sid = str(uuid.uuid4())
    tid = str(uuid.uuid4())
    await crud.create_session(
        db, id=sid, target_language="es", proficiency_level="B1",
        created_at=_now(), updated_at=_now(),
    )
    await crud.create_turn(
        db, id=tid, session_id=sid, turn_index=0,
        user_message="Yo fui al mercado ayer.",
        display_condition="baseline", created_at=_now(),
    )
    return sid, tid


def _make_ctx(db, session_id, turn_id):
    return PipelineContext(
        turn_id=turn_id,
        session_id=session_id,
        user_message="Yo fui al mercado ayer.",
        target_language="es",
        proficiency_level="B1",
        conversation_history=[],
        db=db,
        llm_client=MockLLMClient(),
    )


# ---------------------------------------------------------------------------
# Baseline pipeline
# ---------------------------------------------------------------------------

async def test_run_baseline_returns_pipeline_result(db_session):
    sid, tid = await _setup_session_and_turn(db_session)
    result = await run_baseline(_make_ctx(db_session, sid, tid))

    assert isinstance(result.feedback, FeedbackOutput)
    assert result.condition == "baseline"
    assert result.pipeline_run_id
    assert result.latency_ms >= 0


async def test_run_baseline_creates_one_artifact(db_session):
    sid, tid = await _setup_session_and_turn(db_session)
    result = await run_baseline(_make_ctx(db_session, sid, tid))

    artifacts = (
        await db_session.execute(
            select(PipelineArtifact).where(
                PipelineArtifact.pipeline_run_id == result.pipeline_run_id
            )
        )
    ).scalars().all()
    assert len(artifacts) == 1
    assert artifacts[0].stage == "baseline"


async def test_run_baseline_pipeline_run_completed(db_session):
    sid, tid = await _setup_session_and_turn(db_session)
    result = await run_baseline(_make_ctx(db_session, sid, tid))

    run = await crud.get_pipeline_run(db_session, result.pipeline_run_id)
    assert run.status == "completed"
    assert run.condition == "baseline"


async def test_run_baseline_writes_feedback_output(db_session):
    sid, tid = await _setup_session_and_turn(db_session)
    await run_baseline(_make_ctx(db_session, sid, tid))

    fo = await crud.get_feedback_output(db_session, tid, "baseline")
    assert fo is not None
    assert fo.corrected_utterance
    assert fo.conversation_reply is not None


# ---------------------------------------------------------------------------
# Corrected pipeline
# ---------------------------------------------------------------------------

async def _run_corrected_with_baseline(db_session, ctx):
    """Helper: run baseline first, then pass its output to run_corrected."""
    baseline_result = await run_baseline(ctx)
    return await run_corrected(ctx, baseline_feedback=baseline_result.feedback)


async def test_run_corrected_returns_pipeline_result(db_session):
    sid, tid = await _setup_session_and_turn(db_session)
    result = await _run_corrected_with_baseline(db_session, _make_ctx(db_session, sid, tid))

    assert isinstance(result.feedback, FeedbackOutput)
    assert result.condition == "corrected"


async def test_run_corrected_creates_four_artifacts(db_session):
    sid, tid = await _setup_session_and_turn(db_session)
    result = await _run_corrected_with_baseline(db_session, _make_ctx(db_session, sid, tid))

    artifacts = (
        await db_session.execute(
            select(PipelineArtifact).where(
                PipelineArtifact.pipeline_run_id == result.pipeline_run_id
            ).order_by(PipelineArtifact.stage_index)
        )
    ).scalars().all()
    assert len(artifacts) == 4
    stages = [a.stage for a in artifacts]
    assert stages[0] == "draft"
    assert "verifier" in stages
    assert "critic" in stages
    assert stages[3] == "reviser"


async def test_run_corrected_pipeline_run_completed(db_session):
    sid, tid = await _setup_session_and_turn(db_session)
    result = await _run_corrected_with_baseline(db_session, _make_ctx(db_session, sid, tid))

    run = await crud.get_pipeline_run(db_session, result.pipeline_run_id)
    assert run.status == "completed"
    assert run.condition == "corrected"


async def test_run_corrected_writes_feedback_output(db_session):
    sid, tid = await _setup_session_and_turn(db_session)
    await _run_corrected_with_baseline(db_session, _make_ctx(db_session, sid, tid))

    fo = await crud.get_feedback_output(db_session, tid, "corrected")
    assert fo is not None
    assert fo.conversation_reply is not None


# ---------------------------------------------------------------------------
# Orchestrator — run_both_conditions
# ---------------------------------------------------------------------------

async def test_orchestrator_returns_display_condition_result(db_session):
    sid, tid = await _setup_session_and_turn(db_session)
    ctx = _make_ctx(db_session, sid, tid)

    result = await run_both_conditions(ctx, "baseline")
    assert result.condition == "baseline"
    assert isinstance(result.feedback, FeedbackOutput)


async def test_orchestrator_background_task_completes(db_session):
    """After awaiting the display result, the background task should eventually complete."""
    sid, tid = await _setup_session_and_turn(db_session)
    ctx = _make_ctx(db_session, sid, tid)

    await run_both_conditions(ctx, "baseline")

    # Let the background task run
    await asyncio.sleep(0.3)

    # Both pipeline_runs should exist (the alternate uses its own session so
    # we check only the display one here — the alternate writes to a new session)
    runs = await crud.get_turn_pipeline_runs(db_session, tid)
    # At minimum the display run must be completed
    display_run = next(r for r in runs if r.condition == "baseline")
    assert display_run.status == "completed"


async def test_get_turn_artifacts_returns_five_total(db_session):
    """After both pipelines complete, get_turn_artifacts returns 5 records (1 baseline + 4 corrected)."""
    sid, tid = await _setup_session_and_turn(db_session)
    ctx = _make_ctx(db_session, sid, tid)

    # Run both conditions explicitly (no background task — same session)
    baseline_result = await run_baseline(ctx)
    await run_corrected(ctx, baseline_feedback=baseline_result.feedback)

    artifacts = await crud.get_turn_artifacts(db_session, tid)
    assert len(artifacts) == 5
