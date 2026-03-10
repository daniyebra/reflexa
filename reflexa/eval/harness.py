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


async def run_evaluation(eval_batch_id: str) -> None:
    """
    Run the full evaluation for a batch.  Called as a background asyncio.Task.
    Uses its own DB session (separate from the request session).
    Builds one OpenRouter LLMClient per judge model internally.
    """
    from reflexa.config import settings
    from reflexa.llm.client import build_judge_client

    async with AsyncSessionLocal() as db:
        async with db.begin():
            await crud.update_eval_batch_status(db, eval_batch_id, "running")

    # Pre-fetch all data needed for scoring in a single session
    async with AsyncSessionLocal() as db:
        batch = await crud.get_eval_batch(db, eval_batch_id)
        items = await crud.get_eval_items(db, eval_batch_id)
        judge_models: list[str] = json.loads(batch.judge_models)

        # Self-judging guard
        if settings.llm_model in judge_models:
            raise ValueError(
                f"Pipeline model '{settings.llm_model}' is in the judge pool. "
                "Remove it from JUDGE_MODELS to prevent self-judging."
            )

        # Pre-fetch all feedback outputs and turns
        from reflexa.db.models import FeedbackOutput as FeedbackOutputDB, Turn
        from sqlalchemy import select

        item_data = {}
        for item in items:
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

            item_data[item.id] = {
                "item": item,
                "fo_id": fo.id,
                "user_message": turn.user_message,
                "corrected_utterance": fo.corrected_utterance,
                "error_list_json": fo.error_list,
                "explanations": fo.explanations,
                "prioritization_and_focus": fo.prioritization_and_focus,
                "practice_prompt": fo.practice_prompt,
                "conversation_reply": fo.conversation_reply or "",
            }

    # Build one client per judge model
    judge_clients = {m: build_judge_client(settings, m) for m in judge_models}

    sem = asyncio.Semaphore(_SEMAPHORE_LIMIT)
    total_done = 0
    total_tasks = len(items) * len(judge_models) * len(EVAL_DIMENSIONS)

    async def _score_one(item_id: str, judge_model_id: str, dimension: str) -> None:
        nonlocal total_done
        async with sem:
            data = item_data[item_id]
            # Each scoring task gets its own DB session
            async with AsyncSessionLocal() as score_db:
                await score_item(
                    eval_item_id=item_id,
                    feedback_output_id=data["fo_id"],
                    judge_model_id=judge_model_id,
                    dimension=dimension,
                    user_message=data["user_message"],
                    corrected_utterance=data["corrected_utterance"],
                    error_list_json=data["error_list_json"],
                    explanations=data["explanations"],
                    prioritization_and_focus=data["prioritization_and_focus"],
                    practice_prompt=data["practice_prompt"],
                    conversation_reply=data["conversation_reply"],
                    llm_client=judge_clients[judge_model_id],
                    db=score_db,
                )
                await score_db.commit()
            total_done += 1
            if total_done % 100 == 0:
                logger.info("eval progress: %d/%d", total_done, total_tasks)

    try:
        tasks = [
            _score_one(item.id, judge_model_id, dimension)
            for item in items
            for judge_model_id in judge_models
            for dimension in EVAL_DIMENSIONS
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)
        failures = [r for r in results if isinstance(r, Exception)]
        if failures:
            logger.warning(
                "eval_batch %s: %d/%d scoring tasks failed (continuing with successes)",
                eval_batch_id, len(failures), len(results),
            )
            for f in failures[:5]:
                logger.warning("  sample failure: %s", f)

        async with AsyncSessionLocal() as db2:
            async with db2.begin():
                await crud.update_eval_batch_status(db2, eval_batch_id, "completed")

        logger.info(
            "eval_batch %s completed: %d items × %d models × %d dimensions = %d tasks (%d failed)",
            eval_batch_id, len(items), len(judge_models), len(EVAL_DIMENSIONS),
            len(results), len(failures),
        )

    except Exception as exc:
        logger.exception("eval_batch %s failed: %s", eval_batch_id, exc)
        async with AsyncSessionLocal() as db3:
            async with db3.begin():
                await crud.update_eval_batch_status(db3, eval_batch_id, "failed")
        raise
