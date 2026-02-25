from __future__ import annotations

import logging
from sqlalchemy.ext.asyncio import AsyncSession

from reflexa.prompt_loader import get_prompt
from reflexa.schemas.opener import SessionOpenerOutput

log = logging.getLogger("reflexa.pipeline")


async def run_session_opener(
    *,
    session_id: str,
    target_language: str,
    proficiency_level: str | None,
    db: AsyncSession,
    llm_client,
) -> str:
    """
    Generate an opening message in the target language appropriate to the
    student's proficiency level.

    Returns the opener string.  No PipelineRun row is created (not tied to
    a turn); the LLMCall row is written automatically by the client.
    """
    tmpl = get_prompt("session_opener")
    messages = tmpl.to_messages(
        target_language=target_language,
        proficiency_level=proficiency_level or "unspecified",
    )

    result: SessionOpenerOutput = await llm_client.complete(
        messages=messages,
        response_model=SessionOpenerOutput,
        prompt_version_id=tmpl.version_id,
        caller_context="pipeline/session_opener",
        db=db,
        temperature=tmpl.model_constraints.get("temperature", 0.7),
        max_tokens=tmpl.model_constraints.get("max_tokens", 256),
    )

    log.info("session_opener complete session=%s", session_id)
    return result.message
