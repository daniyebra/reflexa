from __future__ import annotations

import asyncio
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
from reflexa.schemas.pipeline import CriticOutput, VerifierOutput

log = logging.getLogger("reflexa.pipeline")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _feedback_to_text(fb: FeedbackOutput) -> str:
    errors = "\n".join(
        f"  [{e.type}] '{e.span}': {e.description}" for e in fb.error_list
    )
    return (
        f"Corrected utterance: {fb.corrected_utterance}\n"
        f"Errors:\n{errors or '  (none)'}\n"
        f"Explanations: {fb.explanations}\n"
        f"Prioritisation: {fb.prioritization_and_focus}\n"
        f"Practice prompt: {fb.practice_prompt}"
    )


async def run_corrected(
    ctx: PipelineContext,
    baseline_feedback: FeedbackOutput,
) -> PipelineResult:
    """
    Corrected pipeline: takes the baseline feedback as its draft and runs
    verifier → critic → reviser to produce an improved feedback object.

    Stage 0 (draft): baseline_feedback passed through — no LLM call.
    Stage 1+2 (verifier ‖ critic): review the baseline feedback in parallel.
    Stage 3 (reviser): integrate reports to produce the final corrected output.
    """
    run_id = str(uuid.uuid4())
    start = time.monotonic()

    await crud.create_pipeline_run(
        ctx.db,
        id=run_id,
        turn_id=ctx.turn_id,
        condition="corrected",
        status="running",
        started_at=_now(),
    )

    try:
        history_text = ConversationMemory.format_for_prompt(ctx.conversation_history)
        draft_text = _feedback_to_text(baseline_feedback)

        # ── Stage 0: Draft (baseline passthrough — no LLM call) ──────────────
        await crud.create_pipeline_artifact(
            ctx.db,
            id=str(uuid.uuid4()),
            pipeline_run_id=run_id,
            stage="draft",
            stage_index=0,
            prompt_version_id="baseline_passthrough/v1",
            raw_input="",
            raw_output=baseline_feedback.model_dump_json(),
            parsed_output=baseline_feedback.model_dump_json(),
            llm_call_id=None,
            created_at=_now(),
        )

        # ── Stage 1+2: Verifier ‖ Critic (parallel) ──────────────────────────
        verifier_tmpl = get_prompt("pipeline_verifier")
        critic_tmpl = get_prompt("pipeline_critic")

        verifier_msgs = verifier_tmpl.to_messages(
            target_language=ctx.target_language,
            proficiency_level=ctx.proficiency_level or "unspecified",
            user_message=ctx.user_message,
            draft_feedback=draft_text,
        )
        critic_msgs = critic_tmpl.to_messages(
            target_language=ctx.target_language,
            proficiency_level=ctx.proficiency_level or "unspecified",
            user_message=ctx.user_message,
            draft_feedback=draft_text,
        )

        # Use review_client for verifier/critic if available (different model
        # avoids self-review bias); fall back to llm_client for backwards compat.
        review_client = ctx.review_client or ctx.llm_client

        verifier, critic = await asyncio.gather(
            review_client.complete(
                messages=verifier_msgs,
                response_model=VerifierOutput,
                prompt_version_id=verifier_tmpl.version_id,
                caller_context="pipeline/corrected/verifier",
                db=ctx.db,
                temperature=verifier_tmpl.model_constraints.get("temperature", 0.2),
                max_tokens=verifier_tmpl.model_constraints.get("max_tokens", 768),
            ),
            review_client.complete(
                messages=critic_msgs,
                response_model=CriticOutput,
                prompt_version_id=critic_tmpl.version_id,
                caller_context="pipeline/corrected/critic",
                db=ctx.db,
                temperature=critic_tmpl.model_constraints.get("temperature", 0.3),
                max_tokens=critic_tmpl.model_constraints.get("max_tokens", 768),
            ),
        )

        await crud.create_pipeline_artifact(
            ctx.db,
            id=str(uuid.uuid4()),
            pipeline_run_id=run_id,
            stage="verifier",
            stage_index=1,
            prompt_version_id=verifier_tmpl.version_id,
            raw_input=json.dumps(verifier_msgs),
            raw_output=verifier.model_dump_json(),
            parsed_output=verifier.model_dump_json(),
            llm_call_id=None,
            created_at=_now(),
        )
        await crud.create_pipeline_artifact(
            ctx.db,
            id=str(uuid.uuid4()),
            pipeline_run_id=run_id,
            stage="critic",
            stage_index=2,
            prompt_version_id=critic_tmpl.version_id,
            raw_input=json.dumps(critic_msgs),
            raw_output=critic.model_dump_json(),
            parsed_output=critic.model_dump_json(),
            llm_call_id=None,
            created_at=_now(),
        )

        # ── Stage 3: Reviser ──────────────────────────────────────────────────
        reviser_tmpl = get_prompt("pipeline_reviser")
        reviser_msgs = reviser_tmpl.to_messages(
            target_language=ctx.target_language,
            proficiency_level=ctx.proficiency_level or "unspecified",
            user_message=ctx.user_message,
            conversation_history=history_text,
            draft_feedback=draft_text,
            verifier_feedback=verifier.model_dump_json(),
            critic_feedback=critic.model_dump_json(),
        )
        final: FeedbackOutput = await ctx.llm_client.complete(
            messages=reviser_msgs,
            response_model=FeedbackOutput,
            prompt_version_id=reviser_tmpl.version_id,
            caller_context="pipeline/corrected/reviser",
            db=ctx.db,
            temperature=reviser_tmpl.model_constraints.get("temperature", 0.3),
            max_tokens=reviser_tmpl.model_constraints.get("max_tokens", 1024),
        )
        await crud.create_pipeline_artifact(
            ctx.db,
            id=str(uuid.uuid4()),
            pipeline_run_id=run_id,
            stage="reviser",
            stage_index=3,
            prompt_version_id=reviser_tmpl.version_id,
            raw_input=json.dumps(reviser_msgs),
            raw_output=final.model_dump_json(),
            parsed_output=final.model_dump_json(),
            llm_call_id=None,
            created_at=_now(),
        )

        await crud.create_feedback_output(
            ctx.db,
            id=str(uuid.uuid4()),
            turn_id=ctx.turn_id,
            condition="corrected",
            corrected_utterance=final.corrected_utterance,
            error_list=json.dumps([e.model_dump() for e in final.error_list]),
            explanations=final.explanations,
            prioritization_and_focus=final.prioritization_and_focus,
            practice_prompt=final.practice_prompt,
            conversation_reply=final.conversation_reply or None,
            pipeline_run_id=run_id,
            created_at=_now(),
        )

        latency_ms = int((time.monotonic() - start) * 1000)
        await crud.update_pipeline_run_status(
            ctx.db, run_id,
            status="completed",
            completed_at=_now(),
        )
        log.info("corrected complete turn=%s latency_ms=%d", ctx.turn_id, latency_ms)
        return PipelineResult(
            feedback=final,
            pipeline_run_id=run_id,
            condition="corrected",
            latency_ms=latency_ms,
        )

    except Exception as exc:
        await crud.update_pipeline_run_status(
            ctx.db, run_id,
            status="failed",
            completed_at=_now(),
            error_message=str(exc),
        )
        log.error("corrected failed turn=%s error=%s", ctx.turn_id, exc)
        raise
