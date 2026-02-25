"""
MockLLMClient — deterministic client for local development and testing.

Activated when OPENAI_API_KEY=mock.  Never makes real API calls.
Extend _MOCK_DATA in later phases to support additional response_model types.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from reflexa.db import crud

T = TypeVar("T", bound=BaseModel)

# ---------------------------------------------------------------------------
# Mock response registry
# ---------------------------------------------------------------------------
# Keys are Pydantic model class names; values are dicts accepted by model_validate().
# Phases 2+ should call _register() for verifier/critic/reviser/judge models.

_MOCK_DATA: dict[str, dict[str, Any]] = {}


def _register(model_cls: type[BaseModel], data: dict[str, Any]) -> None:
    _MOCK_DATA[model_cls.__name__] = data


def _build_response(response_model: type[T]) -> T:
    name = response_model.__name__
    if name not in _MOCK_DATA:
        raise ValueError(
            f"MockLLMClient: no mock data registered for {name!r}. "
            "Call reflexa.llm.mock._register() to add it."
        )
    return response_model.model_validate(_MOCK_DATA[name])


# ---------------------------------------------------------------------------
# Seed mock data for FeedbackOutput (registered at import time)
# ---------------------------------------------------------------------------

def _seed_feedback_output() -> None:
    from reflexa.schemas.feedback import FeedbackOutput  # local import avoids circularity

    _register(FeedbackOutput, {
        "corrected_utterance": "Fui al mercado ayer y compré muchas verduras.",
        "error_list": [
            {
                "span": "Yo fui",
                "description": (
                    "Redundant subject pronoun. Spanish is a pro-drop language; "
                    "the verb conjugation already encodes the subject."
                ),
                "type": "grammar",
            },
            {
                "span": "vegetables",
                "description": "English word used in a Spanish sentence; use 'verduras'.",
                "type": "vocabulary",
            },
            {
                "span": "muchos",
                "description": "'verduras' is feminine plural, so the adjective must be 'muchas'.",
                "type": "grammar",
            },
        ],
        "explanations": (
            "Spanish verbs encode subject information through their endings, so explicit "
            "pronouns like 'Yo' are only used for emphasis or contrast. Mixing English "
            "vocabulary into a Spanish sentence (code-switching) should be avoided in "
            "formal or assessed contexts. Adjective–noun gender agreement is mandatory "
            "in Spanish: 'verduras' (f. pl.) requires 'muchas', not 'muchos'."
        ),
        "prioritization_and_focus": (
            "Address the English vocabulary first ('vegetables' → 'verduras') as it "
            "causes the most significant comprehension barrier. The gender agreement "
            "error ('muchos' → 'muchas') is the next priority. The redundant pronoun "
            "is a stylistic issue and can be introduced after the other two are mastered."
        ),
        "practice_prompt": (
            "Describe your last visit to a market or supermarket in 3–4 sentences. "
            "Focus on using correct gender agreement with nouns and avoid mixing "
            "languages."
        ),
        "conversation_reply": (
            "¡Muy bien! ¿Qué verduras compraste y para qué receta las vas a usar?"
        ),
    })


def _seed_session_opener() -> None:
    from reflexa.schemas.opener import SessionOpenerOutput  # local import avoids circularity

    _register(SessionOpenerOutput, {
        "message": "¡Hola! ¿Qué hiciste el fin de semana pasado?",
    })


_seed_feedback_output()
_seed_session_opener()


# ---------------------------------------------------------------------------
# MockLLMClient
# ---------------------------------------------------------------------------

class MockLLMClient:
    model_id: str = "mock"

    def __init__(self, fail_times: int = 0) -> None:
        """
        Args:
            fail_times: Number of simulated retries before a successful response.
                        The `retries` field in llm_calls will be set to this value.
        """
        self._fail_times = fail_times

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
        result = _build_response(response_model)
        latency_ms = int((time.monotonic() - start) * 1000)

        await crud.create_llm_call(
            db,
            id=str(uuid.uuid4()),
            model_id=self.model_id,
            prompt_version_id=prompt_version_id,
            caller_context=caller_context,
            tokens_in=128,    # deterministic fake counts
            tokens_out=256,
            latency_ms=latency_ms,
            retries=self._fail_times,
            estimated_cost_usd=None,
            error=None,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        return result
