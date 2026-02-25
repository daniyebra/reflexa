from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from reflexa.api.deps import get_db
from reflexa.db import crud
from reflexa.schemas.api import (
    ArtifactResponse,
    FeedbackDetailResponse,
    TurnArtifactsResponse,
)

router = APIRouter(prefix="/turns", tags=["artifacts"])


@router.get("/{turn_id}/artifacts", response_model=TurnArtifactsResponse)
async def get_turn_artifacts(turn_id: str, db: AsyncSession = Depends(get_db)):
    turn = await crud.get_turn(db, turn_id)
    if not turn:
        raise HTTPException(status_code=404, detail="Turn not found")

    artifacts = await crud.get_turn_artifacts(db, turn_id)

    # Retrieve condition from each artifact's pipeline_run
    run_cache: dict[str, str] = {}

    async def get_condition(run_id: str) -> str:
        if run_id not in run_cache:
            run = await crud.get_pipeline_run(db, run_id)
            run_cache[run_id] = run.condition if run else "unknown"
        return run_cache[run_id]

    items = []
    for a in artifacts:
        condition = await get_condition(a.pipeline_run_id)
        items.append(
            ArtifactResponse(
                id=a.id,
                pipeline_run_id=a.pipeline_run_id,
                condition=condition,
                stage=a.stage,
                stage_index=a.stage_index,
                prompt_version_id=a.prompt_version_id,
                raw_input=a.raw_input,
                raw_output=a.raw_output,
                parsed_output=a.parsed_output,
                llm_call_id=a.llm_call_id,
                created_at=a.created_at,
            )
        )

    return TurnArtifactsResponse(turn_id=turn_id, artifacts=items)


@router.get("/{turn_id}/feedback/{condition}", response_model=FeedbackDetailResponse)
async def get_turn_feedback(
    turn_id: str,
    condition: str,
    db: AsyncSession = Depends(get_db),
):
    if condition not in ("baseline", "corrected"):
        raise HTTPException(status_code=400, detail="condition must be 'baseline' or 'corrected'")

    turn = await crud.get_turn(db, turn_id)
    if not turn:
        raise HTTPException(status_code=404, detail="Turn not found")

    fo = await crud.get_feedback_output(db, turn_id, condition)
    if not fo:
        raise HTTPException(
            status_code=404,
            detail=f"No {condition} feedback output for this turn",
        )

    return FeedbackDetailResponse(
        id=fo.id,
        turn_id=fo.turn_id,
        condition=fo.condition,
        corrected_utterance=fo.corrected_utterance,
        error_list=fo.error_list,
        explanations=fo.explanations,
        prioritization_and_focus=fo.prioritization_and_focus,
        practice_prompt=fo.practice_prompt,
        conversation_reply=fo.conversation_reply,
        pipeline_run_id=fo.pipeline_run_id,
        created_at=fo.created_at,
    )
