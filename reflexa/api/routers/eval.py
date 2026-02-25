"""
Eval harness API routes.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from reflexa.api.deps import get_db, get_llm_client
from reflexa.db import crud
from reflexa.schemas.eval import (
    CreateEvalBatchRequest,
    CreateEvalBatchResponse,
    DimensionStat,
    EvalBatchDetailResponse,
    EvalBatchResultsResponse,
    EvalScoreRecord,
    EvalSummaryResponse,
)

router = APIRouter(prefix="/eval", tags=["eval"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("/batches", status_code=202, response_model=CreateEvalBatchResponse)
async def create_eval_batch(
    req: CreateEvalBatchRequest,
    db: AsyncSession = Depends(get_db),
    llm_client=Depends(get_llm_client),
):
    # Resolve feedback_output_ids
    if req.feedback_output_ids is not None:
        fo_ids = req.feedback_output_ids
    else:
        unscored = await crud.get_unscored_feedback_outputs(db)
        fo_ids = [fo.id for fo in unscored]

    if not fo_ids:
        raise HTTPException(status_code=422, detail="No feedback outputs to evaluate.")

    seed = int(datetime.now(timezone.utc).timestamp())
    batch_id = str(uuid.uuid4())
    notes = req.notes or f"seed={seed}"

    batch = await crud.create_eval_batch(
        db,
        id=batch_id,
        judge_models=json.dumps(req.judge_model_ids),
        notes=notes,
        created_at=_now(),
        status="queued",
    )
    items = await crud.create_eval_items(
        db,
        eval_batch_id=batch_id,
        feedback_output_ids=fo_ids,
        seed=seed,
        created_at=_now(),
    )
    await db.commit()

    # Fire-and-forget background evaluation
    from reflexa.eval.harness import run_evaluation

    asyncio.create_task(run_evaluation(batch_id, llm_client))

    return CreateEvalBatchResponse(
        eval_batch_id=batch_id,
        item_count=len(items),
        status="queued",
    )


@router.get("/batches/{batch_id}", response_model=EvalBatchDetailResponse)
async def get_eval_batch(batch_id: str, db: AsyncSession = Depends(get_db)):
    batch = await crud.get_eval_batch(db, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Eval batch not found")
    count = await crud.get_eval_item_count(db, batch_id)
    return EvalBatchDetailResponse(
        eval_batch_id=batch.id,
        status=batch.status,
        judge_models=json.loads(batch.judge_models),
        notes=batch.notes,
        created_at=batch.created_at,
        item_count=count,
    )


@router.get("/batches/{batch_id}/results", response_model=EvalBatchResultsResponse)
async def get_eval_batch_results(batch_id: str, db: AsyncSession = Depends(get_db)):
    batch = await crud.get_eval_batch(db, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Eval batch not found")

    scores = await crud.get_eval_scores(db, batch_id)

    # Fetch eval_item → feedback_output mapping for batch metadata
    items = await crud.get_eval_items(db, batch_id)
    item_map = {i.id: i for i in items}

    records = [
        EvalScoreRecord(
            eval_score_id=s.id,
            eval_item_id=s.eval_item_id,
            eval_batch_id=batch_id,
            display_order=item_map[s.eval_item_id].display_order,
            feedback_output_id=item_map[s.eval_item_id].feedback_output_id,
            condition="",  # blinded — not populated
            turn_id="",
            judge_model_id=s.judge_model_id,
            judge_prompt_version_id=s.judge_prompt_version_id,
            dimension=s.dimension,
            score=s.score,
            rationale=s.rationale,
            condition_revealed=s.condition_revealed,
            llm_call_id=s.llm_call_id,
            created_at=s.created_at,
        )
        for s in scores
    ]
    return EvalBatchResultsResponse(
        eval_batch_id=batch_id,
        status=batch.status,
        scores=records,
    )


@router.get("/batches/{batch_id}/export")
async def export_eval_batch(
    batch_id: str,
    format: str = "csv",
    db: AsyncSession = Depends(get_db),
):
    batch = await crud.get_eval_batch(db, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Eval batch not found")

    if format not in ("csv", "jsonl"):
        raise HTTPException(status_code=400, detail="format must be 'csv' or 'jsonl'")

    if format == "csv":
        from reflexa.eval.export import stream_csv

        async def _gen():
            async for chunk in stream_csv(db, batch_id):
                yield chunk

        filename = f"eval_batch_{batch_id[:8]}.csv"
        return StreamingResponse(
            _gen(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    else:
        from reflexa.eval.export import stream_jsonl

        async def _gen():
            async for chunk in stream_jsonl(db, batch_id):
                yield chunk

        filename = f"eval_batch_{batch_id[:8]}.jsonl"
        return StreamingResponse(
            _gen(),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


@router.get("/summary", response_model=EvalSummaryResponse)
async def get_eval_summary(db: AsyncSession = Depends(get_db)):
    summary = await crud.get_eval_summary(db)
    stats = [
        DimensionStat(
            condition=row["condition"],
            dimension=row["dimension"],
            n=row["n"],
            mean=row["mean"],
            std=row["std"],
        )
        for row in summary
    ]
    return EvalSummaryResponse(stats=stats)
