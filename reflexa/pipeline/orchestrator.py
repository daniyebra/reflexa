"""
Pipeline orchestrator — runs both conditions for every user turn.

Baseline always runs first (awaited). Its output is then passed to the
corrected pipeline as the draft, so the corrected condition is a direct
improvement of the baseline rather than an independent generation.

If display_condition is "baseline":
  - baseline is awaited and returned; corrected fires as a background task.
If display_condition is "corrected":
  - baseline is awaited silently; corrected is then awaited and returned.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from reflexa.llm.client import LLMClient
    from reflexa.llm.mock import MockLLMClient
    from reflexa.schemas.feedback import FeedbackOutput

log = logging.getLogger("reflexa.pipeline")


@dataclass
class PipelineContext:
    turn_id: str
    session_id: str
    user_message: str
    target_language: str
    proficiency_level: str | None
    conversation_history: list[dict]   # pre-rendered, oldest-first
    db: AsyncSession
    llm_client: "LLMClient | MockLLMClient"
    review_client: "LLMClient | MockLLMClient | None" = None


@dataclass
class PipelineResult:
    feedback: object          # FeedbackOutput
    pipeline_run_id: str
    condition: str
    latency_ms: int


async def _run_corrected_background(
    ctx: PipelineContext,
    baseline_feedback: "FeedbackOutput",
) -> None:
    """
    Execute the corrected pipeline in the background with its own DB session.
    Errors are logged but never propagate to the caller.
    """
    from reflexa.db.engine import AsyncSessionLocal
    from reflexa.pipeline.corrected import run_corrected

    async with AsyncSessionLocal() as db:
        alt_ctx = PipelineContext(
            turn_id=ctx.turn_id,
            session_id=ctx.session_id,
            user_message=ctx.user_message,
            target_language=ctx.target_language,
            proficiency_level=ctx.proficiency_level,
            conversation_history=ctx.conversation_history,
            db=db,
            llm_client=ctx.llm_client,
            review_client=ctx.review_client,
        )
        try:
            await run_corrected(alt_ctx, baseline_feedback=baseline_feedback)
            await db.commit()
        except Exception:
            log.exception(
                "Background pipeline/corrected failed for turn %s", ctx.turn_id
            )
            await db.rollback()


async def run_both_conditions(
    ctx: PipelineContext,
    display_condition: str,
) -> PipelineResult:
    """
    Run both pipeline conditions.

    Baseline always runs first. Its output is passed as the draft to the
    corrected pipeline (verifier → critic → reviser).

    * If display_condition is "baseline": returns the baseline result immediately
      and fires corrected as a background asyncio.Task.
    * If display_condition is "corrected": awaits corrected after baseline and
      returns the corrected result.
    """
    from reflexa.pipeline.baseline import run_baseline
    from reflexa.pipeline.corrected import run_corrected

    # Step 1: always run baseline first
    baseline_result = await run_baseline(ctx)

    if display_condition == "baseline":
        # Step 2a: fire corrected in background using baseline output
        asyncio.create_task(
            _run_corrected_background(ctx, baseline_result.feedback),
            name=f"corrected-pipeline-{ctx.turn_id}",
        )
        return baseline_result
    else:
        # Step 2b: run corrected synchronously and return it
        return await run_corrected(ctx, baseline_feedback=baseline_result.feedback)
