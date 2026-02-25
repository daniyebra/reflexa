"""
Evaluation harness — orchestrates scoring across all (item × model × dimension) triples.
"""
from __future__ import annotations

import asyncio
import json
import logging

from reflexa.db import crud
from reflexa.db.engine import AsyncSessionLocal
from reflexa.eval.judge import EVAL_DIMENSIONS, score_item

logger = logging.getLogger(__name__)

_SEMAPHORE_LIMIT = 10


async def run_evaluation(
    eval_batch_id: str,
    llm_client,
) -> None:
    """
    Run the full evaluation for a batch.  Called as a background asyncio.Task.
    Uses its own DB session (separate from the request session).
    """
    async with AsyncSessionLocal() as db:
        async with db.begin():
            await crud.update_eval_batch_status(db, eval_batch_id, "running")

    async with AsyncSessionLocal() as db:
        try:
            batch = await crud.get_eval_batch(db, eval_batch_id)
            items = await crud.get_eval_items(db, eval_batch_id)
            judge_models: list[str] = json.loads(batch.judge_models)

            sem = asyncio.Semaphore(_SEMAPHORE_LIMIT)

            async def _score_one(item, judge_model_id: str, dimension: str) -> None:
                async with sem:
                    # Load feedback output for this item
                    from reflexa.db.models import FeedbackOutput as FeedbackOutputDB, Turn
                    from sqlalchemy import select

                    fo_result = await db.execute(
                        select(FeedbackOutputDB).where(
                            FeedbackOutputDB.id == item.feedback_output_id
                        )
                    )
                    fo = fo_result.scalar_one()

                    turn_result = await db.execute(
                        select(Turn).where(Turn.id == fo.turn_id)
                    )
                    turn = turn_result.scalar_one()

                    await score_item(
                        eval_item_id=item.id,
                        feedback_output_id=fo.id,
                        judge_model_id=judge_model_id,
                        dimension=dimension,
                        user_message=turn.user_message,
                        corrected_utterance=fo.corrected_utterance,
                        error_list_json=fo.error_list,
                        explanations=fo.explanations,
                        prioritization_and_focus=fo.prioritization_and_focus,
                        practice_prompt=fo.practice_prompt,
                        llm_client=llm_client,
                        db=db,
                    )

            tasks = [
                _score_one(item, judge_model_id, dimension)
                for item in items
                for judge_model_id in judge_models
                for dimension in EVAL_DIMENSIONS
            ]

            await asyncio.gather(*tasks)
            await db.commit()

            async with AsyncSessionLocal() as db2:
                async with db2.begin():
                    await crud.update_eval_batch_status(db2, eval_batch_id, "completed")

            logger.info(
                "eval_batch %s completed: %d items × %d models × %d dimensions = %d scores",
                eval_batch_id, len(items), len(judge_models), len(EVAL_DIMENSIONS),
                len(items) * len(judge_models) * len(EVAL_DIMENSIONS),
            )

        except Exception as exc:
            logger.exception("eval_batch %s failed: %s", eval_batch_id, exc)
            await db.rollback()
            async with AsyncSessionLocal() as db3:
                async with db3.begin():
                    await crud.update_eval_batch_status(db3, eval_batch_id, "failed")
            raise
