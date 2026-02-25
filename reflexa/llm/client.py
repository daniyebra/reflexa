"""
LLMClient — wraps instructor + AsyncOpenAI for structured output with telemetry.

Every call writes one row to llm_calls regardless of success or failure.
Raises LLMCallError on failure after writing the error to that row.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import TypeVar

import instructor
from openai import AsyncOpenAI
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from reflexa.db import crud
from reflexa.llm.cost import estimate_cost

T = TypeVar("T", bound=BaseModel)


class LLMCallError(Exception):
    """Raised when an LLM call fails (after instructor's internal retries)."""


class LLMClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        # max_retries=0 on the OpenAI client — instructor handles validation retries
        raw = AsyncOpenAI(api_key=api_key, max_retries=0)
        self._client = instructor.from_openai(raw)
        self.model_id = model
        self.timeout = timeout
        self.max_retries = max_retries

    async def complete(
        self,
        *,
        messages: list[dict[str, str]],
        response_model: type[T],
        prompt_version_id: str,
        caller_context: str,
        db: AsyncSession,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> T:
        start = time.monotonic()
        tokens_in: int | None = None
        tokens_out: int | None = None
        error_str: str | None = None
        result: T | None = None

        try:
            async with asyncio.timeout(self.timeout):
                result, completion = (
                    await self._client.chat.completions.create_with_completion(
                        model=self.model_id,
                        messages=messages,
                        response_model=response_model,
                        max_retries=self.max_retries,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                )
            if completion.usage:
                tokens_in = completion.usage.prompt_tokens
                tokens_out = completion.usage.completion_tokens
        except Exception as exc:
            error_str = str(exc)
            raise LLMCallError(error_str) from exc
        finally:
            latency_ms = int((time.monotonic() - start) * 1000)
            cost = estimate_cost(self.model_id, tokens_in or 0, tokens_out or 0)
            await crud.create_llm_call(
                db,
                id=str(uuid.uuid4()),
                model_id=self.model_id,
                prompt_version_id=prompt_version_id,
                caller_context=caller_context,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                latency_ms=latency_ms,
                retries=0,   # instructor's internal retries are not surfaced
                estimated_cost_usd=cost,
                error=error_str,
                created_at=datetime.now(timezone.utc).isoformat(),
            )

        return result  # type: ignore[return-value]


def build_llm_client(settings) -> LLMClient | object:
    """Factory used by the FastAPI dependency in Phase 2."""
    from reflexa.llm.mock import MockLLMClient

    if settings.is_mock:
        return MockLLMClient()
    return LLMClient(
        api_key=settings.openai_api_key,
        model=settings.llm_model,
        timeout=settings.llm_timeout,
    )
