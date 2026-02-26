"""
CRUD helpers.

Phase 0: all stubs.
Phase 1: create_llm_call() implemented.
Phase 2: all pipeline/session/turn/artifact functions implemented.
Phase 4: all eval functions implemented.
"""
from __future__ import annotations

import math

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

async def create_session(
    db: AsyncSession,
    *,
    id: str,
    target_language: str,
    proficiency_level: str | None,
    created_at: str,
    updated_at: str,
    metadata: dict | None = None,
    opener_message: str | None = None,
):
    import json
    from reflexa.db.models import Session

    obj = Session(
        id=id,
        target_language=target_language,
        proficiency_level=proficiency_level,
        created_at=created_at,
        updated_at=updated_at,
        metadata_=json.dumps(metadata) if metadata else None,
        opener_message=opener_message,
    )
    db.add(obj)
    await db.flush()
    return obj


async def get_session(db: AsyncSession, session_id: str):
    from reflexa.db.models import Session

    result = await db.execute(select(Session).where(Session.id == session_id))
    return result.scalar_one_or_none()


async def get_session_turn_count(db: AsyncSession, session_id: str) -> int:
    from reflexa.db.models import Turn

    result = await db.execute(
        select(func.count()).select_from(Turn).where(Turn.session_id == session_id)
    )
    return result.scalar() or 0


# ---------------------------------------------------------------------------
# Turns
# ---------------------------------------------------------------------------

async def create_turn(
    db: AsyncSession,
    *,
    id: str,
    session_id: str,
    turn_index: int,
    user_message: str,
    display_condition: str,
    created_at: str,
):
    from reflexa.db.models import Turn

    obj = Turn(
        id=id,
        session_id=session_id,
        turn_index=turn_index,
        user_message=user_message,
        display_condition=display_condition,
        created_at=created_at,
    )
    db.add(obj)
    return obj


async def get_turn(db: AsyncSession, turn_id: str):
    from reflexa.db.models import Turn

    result = await db.execute(select(Turn).where(Turn.id == turn_id))
    return result.scalar_one_or_none()


async def get_next_turn_index(db: AsyncSession, session_id: str) -> int:
    from reflexa.db.models import Turn

    result = await db.execute(
        select(func.max(Turn.turn_index)).where(Turn.session_id == session_id)
    )
    max_idx = result.scalar()
    return 0 if max_idx is None else max_idx + 1


async def get_recent_turns(db: AsyncSession, session_id: str, limit: int) -> list:
    from reflexa.db.models import Turn

    result = await db.execute(
        select(Turn)
        .where(Turn.session_id == session_id)
        .order_by(Turn.turn_index.desc())
        .limit(limit)
    )
    turns = result.scalars().all()
    return list(reversed(turns))


# ---------------------------------------------------------------------------
# Pipeline Runs
# ---------------------------------------------------------------------------

async def create_pipeline_run(
    db: AsyncSession,
    *,
    id: str,
    turn_id: str,
    condition: str,
    status: str,
    started_at: str,
):
    from reflexa.db.models import PipelineRun

    obj = PipelineRun(
        id=id,
        turn_id=turn_id,
        condition=condition,
        status=status,
        started_at=started_at,
    )
    db.add(obj)
    await db.flush()
    return obj


async def get_pipeline_run(db: AsyncSession, run_id: str):
    from reflexa.db.models import PipelineRun

    result = await db.execute(select(PipelineRun).where(PipelineRun.id == run_id))
    return result.scalar_one_or_none()


async def get_turn_pipeline_runs(db: AsyncSession, turn_id: str) -> list:
    from reflexa.db.models import PipelineRun

    result = await db.execute(
        select(PipelineRun).where(PipelineRun.turn_id == turn_id)
    )
    return result.scalars().all()


async def update_pipeline_run_status(
    db: AsyncSession,
    run_id: str,
    *,
    status: str,
    completed_at: str | None = None,
    error_message: str | None = None,
):
    from reflexa.db.models import PipelineRun

    result = await db.execute(select(PipelineRun).where(PipelineRun.id == run_id))
    run = result.scalar_one()
    run.status = status
    if completed_at is not None:
        run.completed_at = completed_at
    if error_message is not None:
        run.error_message = error_message
    await db.flush()
    return run


# ---------------------------------------------------------------------------
# Feedback Outputs
# ---------------------------------------------------------------------------

async def create_feedback_output(
    db: AsyncSession,
    *,
    id: str,
    turn_id: str,
    condition: str,
    corrected_utterance: str,
    error_list: str,
    explanations: str,
    prioritization_and_focus: str,
    practice_prompt: str,
    pipeline_run_id: str,
    created_at: str,
    conversation_reply: str | None = None,
):
    from reflexa.db.models import FeedbackOutput as FeedbackOutputDB

    obj = FeedbackOutputDB(
        id=id,
        turn_id=turn_id,
        condition=condition,
        corrected_utterance=corrected_utterance,
        error_list=error_list,
        explanations=explanations,
        prioritization_and_focus=prioritization_and_focus,
        practice_prompt=practice_prompt,
        conversation_reply=conversation_reply,
        pipeline_run_id=pipeline_run_id,
        created_at=created_at,
    )
    db.add(obj)
    await db.flush()
    return obj


async def get_feedback_output(db: AsyncSession, turn_id: str, condition: str):
    from reflexa.db.models import FeedbackOutput as FeedbackOutputDB

    result = await db.execute(
        select(FeedbackOutputDB).where(
            FeedbackOutputDB.turn_id == turn_id,
            FeedbackOutputDB.condition == condition,
        )
    )
    return result.scalar_one_or_none()


async def get_unscored_feedback_outputs(db: AsyncSession) -> list:
    from reflexa.db.models import FeedbackOutput as FeedbackOutputDB, EvalItem

    scored_ids = select(EvalItem.feedback_output_id)
    result = await db.execute(
        select(FeedbackOutputDB).where(
            FeedbackOutputDB.id.not_in(scored_ids),
            FeedbackOutputDB.error_list != "[]",
        )
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Pipeline Artifacts
# ---------------------------------------------------------------------------

async def create_pipeline_artifact(
    db: AsyncSession,
    *,
    id: str,
    pipeline_run_id: str,
    stage: str,
    stage_index: int,
    prompt_version_id: str,
    raw_input: str,
    raw_output: str,
    parsed_output: str | None,
    llm_call_id: str | None,
    created_at: str,
):
    from reflexa.db.models import PipelineArtifact

    obj = PipelineArtifact(
        id=id,
        pipeline_run_id=pipeline_run_id,
        stage=stage,
        stage_index=stage_index,
        prompt_version_id=prompt_version_id,
        raw_input=raw_input,
        raw_output=raw_output,
        parsed_output=parsed_output,
        llm_call_id=llm_call_id,
        created_at=created_at,
    )
    db.add(obj)
    await db.flush()
    return obj


async def get_turn_artifacts(db: AsyncSession, turn_id: str) -> list:
    from reflexa.db.models import PipelineArtifact, PipelineRun

    result = await db.execute(
        select(PipelineArtifact)
        .join(PipelineRun, PipelineArtifact.pipeline_run_id == PipelineRun.id)
        .where(PipelineRun.turn_id == turn_id)
        .order_by(PipelineRun.condition, PipelineArtifact.stage_index)
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# LLM Calls
# ---------------------------------------------------------------------------

async def create_llm_call(
    db: AsyncSession,
    *,
    id: str,
    model_id: str,
    prompt_version_id: str,
    caller_context: str,
    tokens_in: int | None,
    tokens_out: int | None,
    latency_ms: int | None,
    retries: int,
    estimated_cost_usd: float | None,
    error: str | None,
    created_at: str,
):
    from reflexa.db.models import LLMCall

    call = LLMCall(
        id=id,
        model_id=model_id,
        prompt_version_id=prompt_version_id,
        caller_context=caller_context,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency_ms,
        retries=retries,
        estimated_cost_usd=str(estimated_cost_usd) if estimated_cost_usd is not None else None,
        error=error,
        created_at=created_at,
    )
    db.add(call)
    # No explicit flush: concurrent calls (e.g. asyncio.gather in the corrected pipeline)
    # would race on the same session.  Autoflush triggers before any subsequent query.
    return call


# ---------------------------------------------------------------------------
# Eval Batches
# ---------------------------------------------------------------------------

async def create_eval_batch(
    db: AsyncSession,
    *,
    id: str,
    judge_models: str,
    notes: str | None,
    created_at: str,
    status: str = "queued",
):
    from reflexa.db.models import EvalBatch

    obj = EvalBatch(
        id=id,
        judge_models=judge_models,
        notes=notes,
        created_at=created_at,
        status=status,
    )
    db.add(obj)
    await db.flush()
    return obj


async def get_eval_batch(db: AsyncSession, batch_id: str):
    from reflexa.db.models import EvalBatch

    result = await db.execute(select(EvalBatch).where(EvalBatch.id == batch_id))
    return result.scalar_one_or_none()


async def update_eval_batch_status(db: AsyncSession, batch_id: str, status: str):
    from reflexa.db.models import EvalBatch

    result = await db.execute(select(EvalBatch).where(EvalBatch.id == batch_id))
    batch = result.scalar_one()
    batch.status = status
    await db.flush()
    return batch


# ---------------------------------------------------------------------------
# Eval Items
# ---------------------------------------------------------------------------

async def create_eval_items(
    db: AsyncSession,
    *,
    eval_batch_id: str,
    feedback_output_ids: list[str],
    seed: int,
    created_at: str,
) -> list:
    import random
    import uuid as _uuid
    from reflexa.db.models import EvalItem

    # Shuffle with reproducible seed for blinding
    rng = random.Random(seed)
    shuffled = list(feedback_output_ids)
    rng.shuffle(shuffled)

    items = []
    for display_order, fo_id in enumerate(shuffled, start=1):
        obj = EvalItem(
            id=str(_uuid.uuid4()),
            feedback_output_id=fo_id,
            eval_batch_id=eval_batch_id,
            display_order=display_order,
            created_at=created_at,
        )
        db.add(obj)
        items.append(obj)

    await db.flush()
    return items


async def get_eval_items(db: AsyncSession, batch_id: str) -> list:
    from reflexa.db.models import EvalItem

    result = await db.execute(
        select(EvalItem)
        .where(EvalItem.eval_batch_id == batch_id)
        .order_by(EvalItem.display_order)
    )
    return result.scalars().all()


async def get_eval_item_count(db: AsyncSession, batch_id: str) -> int:
    from reflexa.db.models import EvalItem

    result = await db.execute(
        select(func.count()).select_from(EvalItem).where(EvalItem.eval_batch_id == batch_id)
    )
    return result.scalar() or 0


# ---------------------------------------------------------------------------
# Eval Scores
# ---------------------------------------------------------------------------

async def create_eval_score(
    db: AsyncSession,
    *,
    id: str,
    eval_item_id: str,
    judge_model_id: str,
    judge_prompt_version_id: str,
    dimension: str,
    score: int,
    rationale: str,
    condition_revealed: int = 0,
    llm_call_id: str | None,
    created_at: str,
):
    from reflexa.db.models import EvalScore

    obj = EvalScore(
        id=id,
        eval_item_id=eval_item_id,
        judge_model_id=judge_model_id,
        judge_prompt_version_id=judge_prompt_version_id,
        dimension=dimension,
        score=score,
        rationale=rationale,
        condition_revealed=condition_revealed,
        llm_call_id=llm_call_id,
        created_at=created_at,
    )
    db.add(obj)
    # No explicit flush: avoid "Session is already flushing" race in asyncio.gather.
    return obj


async def get_eval_scores(db: AsyncSession, batch_id: str) -> list:
    from reflexa.db.models import EvalScore, EvalItem

    result = await db.execute(
        select(EvalScore)
        .join(EvalItem, EvalScore.eval_item_id == EvalItem.id)
        .where(EvalItem.eval_batch_id == batch_id)
        .order_by(EvalItem.display_order, EvalScore.dimension)
    )
    return result.scalars().all()


async def get_eval_summary(db: AsyncSession) -> list:
    """
    Return per (condition × dimension) mean and std across all eval_scores.
    Returns a list of dicts: {condition, dimension, n, mean, std}.
    """
    from reflexa.db.models import EvalScore, EvalItem, FeedbackOutput as FeedbackOutputDB

    result = await db.execute(
        select(
            FeedbackOutputDB.condition,
            EvalScore.dimension,
            EvalScore.score,
        )
        .join(EvalItem, EvalScore.eval_item_id == EvalItem.id)
        .join(FeedbackOutputDB, EvalItem.feedback_output_id == FeedbackOutputDB.id)
    )
    rows = result.all()

    # Group by (condition, dimension)
    groups: dict[tuple[str, str], list[int]] = {}
    for condition, dimension, score in rows:
        key = (condition, dimension)
        groups.setdefault(key, []).append(score)

    summary = []
    for (condition, dimension), scores in sorted(groups.items()):
        n = len(scores)
        mean = sum(scores) / n
        variance = sum((s - mean) ** 2 for s in scores) / n
        std = math.sqrt(variance)
        summary.append({
            "condition": condition,
            "dimension": dimension,
            "n": n,
            "mean": mean,
            "std": std,
        })
    return summary
