import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from reflexa.api.deps import get_db, get_llm_client
from reflexa.config import settings
from reflexa.db import crud
from reflexa.pipeline.opener import run_session_opener
from reflexa.schemas.api import (
    CreateSessionRequest,
    SessionDetailResponse,
    SessionHistoryResponse,
    SessionResponse,
    TurnHistoryItem,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("", status_code=201, response_model=SessionResponse)
async def create_session(
    req: CreateSessionRequest,
    db: AsyncSession = Depends(get_db),
    llm_client=Depends(get_llm_client),
):
    opener_message = await run_session_opener(
        session_id="",  # not yet created; session_id only used for logging
        target_language=req.target_language,
        proficiency_level=req.proficiency_level,
        db=db,
        llm_client=llm_client,
    )

    session = await crud.create_session(
        db,
        id=str(uuid.uuid4()),
        target_language=req.target_language,
        proficiency_level=req.proficiency_level,
        created_at=_now(),
        updated_at=_now(),
        opener_message=opener_message,
    )
    return SessionResponse(
        id=session.id,
        target_language=session.target_language,
        proficiency_level=session.proficiency_level,
        created_at=session.created_at,
        opener_message=session.opener_message,
    )


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)):
    session = await crud.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    count = await crud.get_session_turn_count(db, session_id)
    return SessionDetailResponse(
        id=session.id,
        target_language=session.target_language,
        proficiency_level=session.proficiency_level,
        created_at=session.created_at,
        turn_count=count,
    )


@router.get("/{session_id}/history", response_model=SessionHistoryResponse)
async def get_session_history(session_id: str, db: AsyncSession = Depends(get_db)):
    session = await crud.get_session(db, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    turns = await crud.get_recent_turns(db, session_id, settings.memory_turns)
    return SessionHistoryResponse(
        turns=[
            TurnHistoryItem(
                turn_id=t.id,
                turn_index=t.turn_index,
                user_message=t.user_message,
                display_condition=t.display_condition,
                created_at=t.created_at,
            )
            for t in turns
        ]
    )
