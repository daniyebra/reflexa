"""
Single LLM judge call for one (eval_item, judge_model, dimension) triple.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from reflexa.db import crud
from reflexa.schemas.eval import JudgeOutput

# ---------------------------------------------------------------------------
# Dimension descriptions (for the judge prompt)
# ---------------------------------------------------------------------------

EVAL_DIMENSIONS: dict[str, str] = {
    "linguistic_correctness": (
        "Are the corrections accurate? Are there any spurious corrections or "
        "missed errors? Does the corrected utterance properly fix all linguistic issues?"
    ),
    "explanation_quality": (
        "Are the explanations clear, specific, and tied to each identified error? "
        "Do they help the learner understand why the error is wrong?"
    ),
    "actionability": (
        "Is the practice prompt useful and targeted at the identified errors? "
        "Would following it help the learner improve?"
    ),
    "level_appropriateness": (
        "Is the complexity of the feedback matched to the learner's proficiency level? "
        "Is it neither too simple nor too advanced?"
    ),
    "prioritization_and_focus": (
        "Are the most important errors correctly prioritized? "
        "Is the focus on issues that matter most for communication at this level?"
    ),
    "conversational_quality": (
        "Does the conversational reply engage naturally with the student's message? "
        "Is it at the right proficiency level, encouraging, and does it end with an "
        "open-ended question that drives further conversation?"
    ),
}


async def score_item(
    *,
    eval_item_id: str,
    feedback_output_id: str,
    judge_model_id: str,
    dimension: str,
    user_message: str,
    corrected_utterance: str,
    error_list_json: str,
    explanations: str,
    prioritization_and_focus: str,
    practice_prompt: str,
    conversation_reply: str = "",
    llm_client,
    db: AsyncSession,
) -> None:
    """
    Call the judge LLM for one (item, model, dimension) and persist the score.
    NOTE: condition is deliberately NOT passed to the judge (blinding).
    """
    from reflexa.prompt_loader import get_prompt

    prompt = get_prompt("eval_judge")
    dimension_description = EVAL_DIMENSIONS[dimension]

    messages = prompt.to_messages(
        dimension=dimension,
        dimension_description=dimension_description,
        user_message=user_message,
        corrected_utterance=corrected_utterance,
        error_list=error_list_json,
        explanations=explanations,
        prioritization_and_focus=prioritization_and_focus,
        practice_prompt=practice_prompt,
        conversation_reply=conversation_reply,
    )

    now = datetime.now(timezone.utc).isoformat()
    score_id = str(uuid.uuid4())

    # Use a unique caller_context per call to avoid race conditions in gather
    unique_context = f"eval/judge/{dimension}/{score_id}"

    judge_output: JudgeOutput = await llm_client.complete(
        messages=messages,
        response_model=JudgeOutput,
        prompt_version_id=prompt.version_id,
        caller_context=unique_context,
        db=db,
    )

    # Retrieve the llm_call we just inserted using the unique context.
    # No explicit flush: autoflush=True triggers before the select, matching the pattern
    # used in create_llm_call to avoid "Session is already flushing" races in gather.
    from reflexa.db.models import LLMCall
    from sqlalchemy import select, desc

    llm_call_result = await db.execute(
        select(LLMCall)
        .where(LLMCall.caller_context == unique_context)
        .order_by(desc(LLMCall.created_at))
        .limit(1)
    )
    llm_call = llm_call_result.scalar_one_or_none()
    llm_call_id = llm_call.id if llm_call else None

    await crud.create_eval_score(
        db,
        id=score_id,
        eval_item_id=eval_item_id,
        judge_model_id=judge_model_id,
        judge_prompt_version_id=prompt.version_id,
        dimension=dimension,
        score=judge_output.score,
        rationale=judge_output.rationale,
        condition_revealed=0,
        llm_call_id=llm_call_id,
        created_at=now,
    )
