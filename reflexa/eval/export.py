"""
CSV / JSONL streaming export for eval batch results.
"""
from __future__ import annotations

import csv
import io
import json
from typing import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from reflexa.db.models import (
    EvalBatch, EvalItem, EvalScore,
    FeedbackOutput as FeedbackOutputDB, Turn,
)

# Export column order matches PRD §10.4
_COLUMNS = [
    "eval_score_id", "eval_item_id", "eval_batch_id", "display_order",
    "feedback_output_id", "condition", "turn_id", "session_id",
    "target_language", "proficiency_level", "user_message",
    "corrected_utterance", "error_list_json", "explanations",
    "prioritization_and_focus", "practice_prompt",
    "judge_model_id", "judge_prompt_version_id",
    "dimension", "score", "rationale", "condition_revealed",
    "llm_call_id", "created_at",
]


async def _iter_rows(db: AsyncSession, batch_id: str):
    """Yield one dict per eval_score row with all required join columns."""
    result = await db.execute(
        select(
            EvalScore,
            EvalItem.display_order,
            EvalItem.feedback_output_id,
            EvalItem.eval_batch_id,
            FeedbackOutputDB.condition,
            FeedbackOutputDB.turn_id,
            FeedbackOutputDB.corrected_utterance,
            FeedbackOutputDB.error_list,
            FeedbackOutputDB.explanations,
            FeedbackOutputDB.prioritization_and_focus,
            FeedbackOutputDB.practice_prompt,
            Turn.session_id,
            Turn.user_message,
        )
        .join(EvalItem, EvalScore.eval_item_id == EvalItem.id)
        .join(FeedbackOutputDB, EvalItem.feedback_output_id == FeedbackOutputDB.id)
        .join(Turn, FeedbackOutputDB.turn_id == Turn.id)
        .where(EvalItem.eval_batch_id == batch_id)
        .order_by(EvalItem.display_order, EvalScore.dimension)
    )
    rows = result.all()

    # Fetch session info for each turn
    from reflexa.db.models import Session as SessionDB
    session_cache: dict[str, SessionDB] = {}

    for row in rows:
        score = row[0]
        session_id: str = row.session_id
        if session_id not in session_cache:
            sess_result = await db.execute(
                select(SessionDB).where(SessionDB.id == session_id)
            )
            session_cache[session_id] = sess_result.scalar_one()
        sess = session_cache[session_id]

        yield {
            "eval_score_id": score.id,
            "eval_item_id": score.eval_item_id,
            "eval_batch_id": row.eval_batch_id,
            "display_order": row.display_order,
            "feedback_output_id": row.feedback_output_id,
            "condition": row.condition,
            "turn_id": row.turn_id,
            "session_id": session_id,
            "target_language": sess.target_language,
            "proficiency_level": sess.proficiency_level or "",
            "user_message": row.user_message,
            "corrected_utterance": row.corrected_utterance,
            "error_list_json": row.error_list,
            "explanations": row.explanations,
            "prioritization_and_focus": row.prioritization_and_focus,
            "practice_prompt": row.practice_prompt,
            "judge_model_id": score.judge_model_id,
            "judge_prompt_version_id": score.judge_prompt_version_id,
            "dimension": score.dimension,
            "score": score.score,
            "rationale": score.rationale,
            "condition_revealed": score.condition_revealed,
            "llm_call_id": score.llm_call_id or "",
            "created_at": score.created_at,
        }


async def stream_csv(db: AsyncSession, batch_id: str) -> AsyncIterator[str]:
    """Yield CSV lines (header + data rows) one at a time."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_COLUMNS, lineterminator="\n")
    writer.writeheader()
    yield buf.getvalue()

    async for row in _iter_rows(db, batch_id):
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=_COLUMNS, lineterminator="\n")
        writer.writerow({k: row.get(k, "") for k in _COLUMNS})
        yield buf.getvalue()


async def stream_jsonl(db: AsyncSession, batch_id: str) -> AsyncIterator[str]:
    """Yield one JSON line per score row."""
    async for row in _iter_rows(db, batch_id):
        yield json.dumps(row, ensure_ascii=False) + "\n"
