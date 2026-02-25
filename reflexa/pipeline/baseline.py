from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone

from reflexa.db import crud
from reflexa.memory import ConversationMemory
from reflexa.pipeline.orchestrator import PipelineContext, PipelineResult
from reflexa.prompt_loader import get_prompt
from reflexa.schemas.feedback import FeedbackOutput

log = logging.getLogger("reflexa.pipeline")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def run_baseline(ctx: PipelineContext) -> PipelineResult:
    run_id = str(uuid.uuid4())
    start = time.monotonic()

    await crud.create_pipeline_run(
        ctx.db,
        id=run_id,
        turn_id=ctx.turn_id,
        condition="baseline",
        status="running",
        started_at=_now(),
    )

    try:
        tmpl = get_prompt("baseline")
        messages = tmpl.to_messages(
            target_language=ctx.target_language,
            proficiency_level=ctx.proficiency_level or "unspecified",
            user_message=ctx.user_message,
            conversation_history=ConversationMemory.format_for_prompt(
                ctx.conversation_history
            ),
        )

        result: FeedbackOutput = await ctx.llm_client.complete(
            messages=messages,
            response_model=FeedbackOutput,
            prompt_version_id=tmpl.version_id,
            caller_context="pipeline/baseline",
            db=ctx.db,
            temperature=tmpl.model_constraints.get("temperature", 0.3),
            max_tokens=tmpl.model_constraints.get("max_tokens", 1024),
        )

        await crud.create_pipeline_artifact(
            ctx.db,
            id=str(uuid.uuid4()),
            pipeline_run_id=run_id,
            stage="baseline",
            stage_index=0,
            prompt_version_id=tmpl.version_id,
            raw_input=json.dumps(messages),
            raw_output=result.model_dump_json(),
            parsed_output=result.model_dump_json(),
            llm_call_id=None,
            created_at=_now(),
        )

        await crud.create_feedback_output(
            ctx.db,
            id=str(uuid.uuid4()),
            turn_id=ctx.turn_id,
            condition="baseline",
            corrected_utterance=result.corrected_utterance,
            error_list=json.dumps([e.model_dump() for e in result.error_list]),
            explanations=result.explanations,
            prioritization_and_focus=result.prioritization_and_focus,
            practice_prompt=result.practice_prompt,
            conversation_reply=result.conversation_reply or None,
            pipeline_run_id=run_id,
            created_at=_now(),
        )

        latency_ms = int((time.monotonic() - start) * 1000)
        await crud.update_pipeline_run_status(
            ctx.db, run_id,
            status="completed",
            completed_at=_now(),
        )
        log.info("baseline complete turn=%s latency_ms=%d", ctx.turn_id, latency_ms)
        return PipelineResult(
            feedback=result,
            pipeline_run_id=run_id,
            condition="baseline",
            latency_ms=latency_ms,
        )

    except Exception as exc:
        await crud.update_pipeline_run_status(
            ctx.db, run_id,
            status="failed",
            completed_at=_now(),
            error_message=str(exc),
        )
        log.error("baseline failed turn=%s error=%s", ctx.turn_id, exc)
        raise
