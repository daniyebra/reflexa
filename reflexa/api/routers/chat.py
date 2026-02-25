import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from reflexa.api.deps import get_db, get_llm_client
from reflexa.config import settings
from reflexa.db import crud
from reflexa.llm.client import LLMCallError
from reflexa.memory import ConversationMemory
from reflexa.pipeline.orchestrator import PipelineContext, run_both_conditions
from reflexa.schemas.api import (
    CreateTurnRequest,
    CreateTurnResponse,
    ErrorItemResponse,
    FeedbackResponse,
)
from reflexa.schemas.feedback import FeedbackOutput

log = logging.getLogger("reflexa.pipeline")

router = APIRouter(prefix="/sessions", tags=["chat"])

_memory = ConversationMemory(max_turns=settings.memory_turns)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("/{session_id}/turns", status_code=201, response_model=CreateTurnResponse)
async def create_turn(
    session_id: str,
    req: CreateTurnRequest,
    db: AsyncSession = Depends(get_db),
    llm_client=Depends(get_llm_client),
):
    if len(req.user_message) > settings.max_message_length:
        raise HTTPException(
            status_code=422,
            detail=f"user_message exceeds {settings.max_message_length} characters",
        )

    session = await crud.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    display_condition = settings.display_condition
    turn_index = await crud.get_next_turn_index(db, session_id)
    turn_id = str(uuid.uuid4())

    await crud.create_turn(
        db,
        id=turn_id,
        session_id=session_id,
        turn_index=turn_index,
        user_message=req.user_message,
        display_condition=display_condition,
        created_at=_now(),
    )

    history = await _memory.get_history(db, session_id, display_condition)

    ctx = PipelineContext(
        turn_id=turn_id,
        session_id=session_id,
        user_message=req.user_message,
        target_language=session.target_language,
        proficiency_level=session.proficiency_level,
        conversation_history=history,
        db=db,
        llm_client=llm_client,
    )

    try:
        result = await run_both_conditions(ctx, display_condition)
    except LLMCallError as exc:
        log.error("Display pipeline failed for turn %s: %s", turn_id, exc)
        raise HTTPException(
            status_code=503,
            detail={"code": "pipeline_error", "message": "Pipeline failed; please retry."},
        )
    feedback: FeedbackOutput = result.feedback

    return CreateTurnResponse(
        turn_id=turn_id,
        turn_index=turn_index,
        feedback=FeedbackResponse(
            turn_id=turn_id,
            condition=result.condition,
            corrected_utterance=feedback.corrected_utterance,
            error_list=[
                ErrorItemResponse(span=e.span, description=e.description, type=e.type)
                for e in feedback.error_list
            ],
            explanations=feedback.explanations,
            prioritization_and_focus=feedback.prioritization_and_focus,
            practice_prompt=feedback.practice_prompt,
            conversation_reply=feedback.conversation_reply,
            pipeline_run_id=result.pipeline_run_id,
            latency_ms=result.latency_ms,
        ),
    )
