"""
Pipeline orchestrator — runs both conditions for every user turn.

The display-condition coroutine is awaited (blocking the HTTP response).
The alternate condition runs as a fire-and-forget asyncio.Task with its
own DB session so it can complete after the response is sent.
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


@dataclass
class PipelineResult:
    feedback: object          # FeedbackOutput
    pipeline_run_id: str
    condition: str
    latency_ms: int


async def _run_alternate(ctx: PipelineContext, condition: str) -> None:
    """
    Execute the alternate condition with its own DB session.
    Errors are logged but never propagate to the caller.
    """
    from reflexa.db.engine import AsyncSessionLocal
    from reflexa.pipeline.baseline import run_baseline
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
        )
        try:
            if condition == "baseline":
                await run_baseline(alt_ctx)
            else:
                await run_corrected(alt_ctx)
            await db.commit()
        except Exception:
            log.exception("Background pipeline/%s failed for turn %s", condition, ctx.turn_id)
            await db.rollback()


async def run_both_conditions(
    ctx: PipelineContext,
    display_condition: str,
) -> PipelineResult:
    """
    Run both pipeline conditions.

    * Awaits the display condition (blocks until done).
    * Fires the alternate condition as a background asyncio.Task.

    Returns the PipelineResult for the display condition only.
    """
    from reflexa.pipeline.baseline import run_baseline
    from reflexa.pipeline.corrected import run_corrected

    alternate_condition = "corrected" if display_condition == "baseline" else "baseline"

    # Launch alternate as a background task (non-blocking)
    asyncio.create_task(
        _run_alternate(ctx, alternate_condition),
        name=f"alt-pipeline-{ctx.turn_id}",
    )

    # Await the display condition
    if display_condition == "baseline":
        return await run_baseline(ctx)
    else:
        return await run_corrected(ctx)
