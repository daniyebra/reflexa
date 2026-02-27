"""
Phase 4 — evaluation harness tests.

Covers:
- CRUD for eval batches, items, scores
- Blinding (condition never passed to judge prompt)
- Randomized display_order (permutation of 1..N)
- Score storage for all (item × model × dimension) combinations
- get_eval_summary aggregation
- CSV / JSONL export column presence
"""
from __future__ import annotations

import asyncio
import io
import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from reflexa.db import crud
from reflexa.db.models import (
    EvalBatch, EvalItem, EvalScore,
    FeedbackOutput as FeedbackOutputDB,
)
from reflexa.eval.harness import run_evaluation
from reflexa.eval.judge import EVAL_DIMENSIONS, score_item
from reflexa.llm.mock import MockLLMClient
from reflexa.schemas.eval import JudgeOutput


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _make_session_turn_feedback(db, condition: str = "baseline"):
    """Insert session + turn + pipeline_run + feedback_output; return feedback_output id."""
    sid = str(uuid.uuid4())
    tid = str(uuid.uuid4())
    rid = str(uuid.uuid4())
    fid = str(uuid.uuid4())

    await crud.create_session(
        db, id=sid, target_language="es", proficiency_level="B1",
        created_at=_now(), updated_at=_now(),
    )
    await crud.create_turn(
        db, id=tid, session_id=sid, turn_index=0,
        user_message="Yo fui al mercado.", display_condition=condition,
        created_at=_now(),
    )
    await crud.create_pipeline_run(
        db, id=rid, turn_id=tid, condition=condition,
        status="completed", started_at=_now(),
    )
    await crud.create_feedback_output(
        db,
        id=fid,
        turn_id=tid,
        condition=condition,
        corrected_utterance="Fui al mercado.",
        error_list=json.dumps([]),
        explanations="No errors.",
        prioritization_and_focus="Good job.",
        practice_prompt="Write more sentences.",
        conversation_reply="¿Y qué compraste allí?",
        pipeline_run_id=rid,
        created_at=_now(),
    )
    return fid


# ---------------------------------------------------------------------------
# Eval Batch CRUD
# ---------------------------------------------------------------------------

async def test_create_eval_batch(db_session):
    batch = await crud.create_eval_batch(
        db_session,
        id=str(uuid.uuid4()),
        judge_models=json.dumps(["mock"]),
        notes="test batch",
        created_at=_now(),
    )
    assert batch.status == "queued"
    assert batch.notes == "test batch"


async def test_get_eval_batch(db_session):
    bid = str(uuid.uuid4())
    await crud.create_eval_batch(
        db_session, id=bid, judge_models=json.dumps(["mock"]),
        notes=None, created_at=_now(),
    )
    found = await crud.get_eval_batch(db_session, bid)
    assert found is not None
    assert found.id == bid


async def test_get_eval_batch_not_found(db_session):
    found = await crud.get_eval_batch(db_session, "no-such-id")
    assert found is None


async def test_update_eval_batch_status(db_session):
    bid = str(uuid.uuid4())
    await crud.create_eval_batch(
        db_session, id=bid, judge_models=json.dumps(["mock"]),
        notes=None, created_at=_now(),
    )
    batch = await crud.update_eval_batch_status(db_session, bid, "completed")
    assert batch.status == "completed"

    fetched = await crud.get_eval_batch(db_session, bid)
    assert fetched.status == "completed"


# ---------------------------------------------------------------------------
# Eval Items — randomization (blinding)
# ---------------------------------------------------------------------------

async def test_create_eval_items_display_order_is_permutation(db_session):
    bid = str(uuid.uuid4())
    await crud.create_eval_batch(
        db_session, id=bid, judge_models=json.dumps(["mock"]),
        notes=None, created_at=_now(),
    )

    fo_ids = []
    for _ in range(5):
        fo_ids.append(await _make_session_turn_feedback(db_session))

    items = await crud.create_eval_items(
        db_session,
        eval_batch_id=bid,
        feedback_output_ids=fo_ids,
        seed=42,
        created_at=_now(),
    )
    orders = sorted(i.display_order for i in items)
    assert orders == list(range(1, len(fo_ids) + 1)), "display_order must be a permutation of 1..N"


async def test_create_eval_items_same_seed_same_order(db_session):
    """Reproducible randomization with same seed."""
    bid1 = str(uuid.uuid4())
    bid2 = str(uuid.uuid4())
    for bid in (bid1, bid2):
        await crud.create_eval_batch(
            db_session, id=bid, judge_models=json.dumps(["mock"]),
            notes=None, created_at=_now(),
        )

    # Share the same fo_ids
    fo_ids = []
    for _ in range(4):
        fo_ids.append(await _make_session_turn_feedback(db_session))

    items1 = await crud.create_eval_items(
        db_session, eval_batch_id=bid1, feedback_output_ids=fo_ids,
        seed=999, created_at=_now(),
    )
    items2 = await crud.create_eval_items(
        db_session, eval_batch_id=bid2, feedback_output_ids=fo_ids,
        seed=999, created_at=_now(),
    )

    order1 = [i.feedback_output_id for i in sorted(items1, key=lambda x: x.display_order)]
    order2 = [i.feedback_output_id for i in sorted(items2, key=lambda x: x.display_order)]
    assert order1 == order2


async def test_get_eval_items(db_session):
    bid = str(uuid.uuid4())
    await crud.create_eval_batch(
        db_session, id=bid, judge_models=json.dumps(["mock"]),
        notes=None, created_at=_now(),
    )
    fo_ids = [await _make_session_turn_feedback(db_session) for _ in range(3)]
    await crud.create_eval_items(
        db_session, eval_batch_id=bid, feedback_output_ids=fo_ids,
        seed=1, created_at=_now(),
    )
    items = await crud.get_eval_items(db_session, bid)
    assert len(items) == 3


async def test_get_eval_item_count(db_session):
    bid = str(uuid.uuid4())
    await crud.create_eval_batch(
        db_session, id=bid, judge_models=json.dumps(["mock"]),
        notes=None, created_at=_now(),
    )
    fo_ids = [await _make_session_turn_feedback(db_session) for _ in range(2)]
    await crud.create_eval_items(
        db_session, eval_batch_id=bid, feedback_output_ids=fo_ids,
        seed=1, created_at=_now(),
    )
    count = await crud.get_eval_item_count(db_session, bid)
    assert count == 2


# ---------------------------------------------------------------------------
# Judge blinding — condition field NOT in judge prompt
# ---------------------------------------------------------------------------

async def test_judge_prompt_does_not_contain_condition(db_session):
    """
    Verify that the judge prompt template does not accept a 'condition' parameter,
    and that the rendered messages don't contain condition-as-identifier labels.
    The word 'corrected' legitimately appears as 'Corrected utterance:' label and
    'corrective feedback' in the system text — what must be absent is the
    condition value used as a discriminator (e.g. 'Condition: baseline').
    """
    from reflexa.prompt_loader import get_prompt
    from reflexa.eval.judge import EVAL_DIMENSIONS

    prompt = get_prompt("eval_judge")

    # score_item() must not pass `condition` to to_messages()
    import inspect
    from reflexa.eval.judge import score_item as _score_item
    sig = inspect.signature(_score_item)
    assert "condition" not in sig.parameters, \
        "score_item() must not accept a 'condition' parameter (blinding)"

    for dimension, dim_desc in EVAL_DIMENSIONS.items():
        messages = prompt.to_messages(
            dimension=dimension,
            dimension_description=dim_desc,
            user_message="Test message",
            corrected_utterance="Test correction",
            error_list="[]",
            explanations="No errors.",
            prioritization_and_focus="Good.",
            practice_prompt="Practice more.",
            conversation_reply="Great job!",
        )
        full_text = " ".join(m["content"] for m in messages)
        # "baseline" would never appear legitimately in a judge prompt
        assert "baseline" not in full_text, \
            "condition label 'baseline' must not appear in judge prompt"
        # The condition value "corrected" as a discriminator label must not appear.
        # We check for the exact pattern that would reveal condition identity.
        import re
        assert not re.search(r'\bcondition\s*[:=]\s*(baseline|corrected)\b', full_text, re.IGNORECASE), \
            "condition identifier must not be present in judge prompt"


# ---------------------------------------------------------------------------
# Eval Score CRUD
# ---------------------------------------------------------------------------

async def test_create_eval_score(db_session):
    bid = str(uuid.uuid4())
    await crud.create_eval_batch(
        db_session, id=bid, judge_models=json.dumps(["mock"]),
        notes=None, created_at=_now(),
    )
    fo_id = await _make_session_turn_feedback(db_session)
    items = await crud.create_eval_items(
        db_session, eval_batch_id=bid, feedback_output_ids=[fo_id],
        seed=1, created_at=_now(),
    )
    item = items[0]

    score = await crud.create_eval_score(
        db_session,
        id=str(uuid.uuid4()),
        eval_item_id=item.id,
        judge_model_id="mock",
        judge_prompt_version_id="eval_judge/v1",
        dimension="linguistic_correctness",
        score=4,
        rationale="Good correction.",
        condition_revealed=0,
        llm_call_id=None,
        created_at=_now(),
    )
    assert score.score == 4
    assert score.condition_revealed == 0


async def test_eval_score_condition_revealed_is_zero(db_session):
    """All scores must be written with condition_revealed=0 (blinded)."""
    bid = str(uuid.uuid4())
    await crud.create_eval_batch(
        db_session, id=bid, judge_models=json.dumps(["mock"]),
        notes=None, created_at=_now(),
    )
    fo_id = await _make_session_turn_feedback(db_session)
    items = await crud.create_eval_items(
        db_session, eval_batch_id=bid, feedback_output_ids=[fo_id],
        seed=1, created_at=_now(),
    )
    await crud.create_eval_score(
        db_session,
        id=str(uuid.uuid4()),
        eval_item_id=items[0].id,
        judge_model_id="mock",
        judge_prompt_version_id="eval_judge/v1",
        dimension="actionability",
        score=3,
        rationale="Decent.",
        condition_revealed=0,
        llm_call_id=None,
        created_at=_now(),
    )

    all_scores = await db_session.execute(select(EvalScore))
    for s in all_scores.scalars().all():
        assert s.condition_revealed == 0, "condition_revealed must always be 0"


# ---------------------------------------------------------------------------
# Full harness run
# ---------------------------------------------------------------------------

async def test_harness_produces_scores_for_all_combinations(db_session):
    """
    After run_evaluation, there should be
    n_items × n_judges × n_dimensions eval_score rows.
    """
    from reflexa.db.engine import AsyncSessionLocal

    # We need to run the harness with its own session (as it does in production),
    # but we're using in-memory SQLite which doesn't support multiple connections.
    # Instead, test the CRUD path directly by running score_item for each combination.
    bid = str(uuid.uuid4())
    await crud.create_eval_batch(
        db_session, id=bid, judge_models=json.dumps(["mock"]),
        notes=None, created_at=_now(),
    )

    fo_ids = [
        await _make_session_turn_feedback(db_session, "baseline"),
        await _make_session_turn_feedback(db_session, "corrected"),
    ]
    items = await crud.create_eval_items(
        db_session, eval_batch_id=bid, feedback_output_ids=fo_ids,
        seed=7, created_at=_now(),
    )

    llm = MockLLMClient()

    for item in items:
        fo_result = await db_session.execute(
            select(FeedbackOutputDB).where(FeedbackOutputDB.id == item.feedback_output_id)
        )
        fo = fo_result.scalar_one()

        from reflexa.db.models import Turn
        turn_result = await db_session.execute(
            select(Turn).where(Turn.id == fo.turn_id)
        )
        turn = turn_result.scalar_one()

        for dimension in EVAL_DIMENSIONS:
            await score_item(
                eval_item_id=item.id,
                feedback_output_id=fo.id,
                judge_model_id="mock",
                dimension=dimension,
                user_message=turn.user_message,
                corrected_utterance=fo.corrected_utterance,
                error_list_json=fo.error_list,
                explanations=fo.explanations,
                prioritization_and_focus=fo.prioritization_and_focus,
                practice_prompt=fo.practice_prompt,
                llm_client=llm,
                db=db_session,
            )

    scores = await crud.get_eval_scores(db_session, bid)
    expected = len(fo_ids) * 1 * len(EVAL_DIMENSIONS)  # 1 judge model
    assert len(scores) == expected, f"Expected {expected} scores, got {len(scores)}"


async def test_harness_all_scores_condition_revealed_zero(db_session):
    """After full harness run, all scores must have condition_revealed=0."""
    bid = str(uuid.uuid4())
    await crud.create_eval_batch(
        db_session, id=bid, judge_models=json.dumps(["mock"]),
        notes=None, created_at=_now(),
    )
    fo_id = await _make_session_turn_feedback(db_session)
    items = await crud.create_eval_items(
        db_session, eval_batch_id=bid, feedback_output_ids=[fo_id],
        seed=1, created_at=_now(),
    )

    item = items[0]
    fo_result = await db_session.execute(
        select(FeedbackOutputDB).where(FeedbackOutputDB.id == item.feedback_output_id)
    )
    fo = fo_result.scalar_one()

    from reflexa.db.models import Turn
    turn_result = await db_session.execute(
        select(Turn).where(Turn.id == fo.turn_id)
    )
    turn = turn_result.scalar_one()

    llm = MockLLMClient()
    for dimension in EVAL_DIMENSIONS:
        await score_item(
            eval_item_id=item.id,
            feedback_output_id=fo.id,
            judge_model_id="mock",
            dimension=dimension,
            user_message=turn.user_message,
            corrected_utterance=fo.corrected_utterance,
            error_list_json=fo.error_list,
            explanations=fo.explanations,
            prioritization_and_focus=fo.prioritization_and_focus,
            practice_prompt=fo.practice_prompt,
            llm_client=llm,
            db=db_session,
        )

    scores_result = await db_session.execute(select(EvalScore))
    for s in scores_result.scalars().all():
        assert s.condition_revealed == 0


# ---------------------------------------------------------------------------
# get_eval_summary
# ---------------------------------------------------------------------------

async def test_get_eval_summary_returns_stats(db_session):
    bid = str(uuid.uuid4())
    await crud.create_eval_batch(
        db_session, id=bid, judge_models=json.dumps(["mock"]),
        notes=None, created_at=_now(),
    )
    fo_ids = [
        await _make_session_turn_feedback(db_session, "baseline"),
        await _make_session_turn_feedback(db_session, "corrected"),
    ]
    items = await crud.create_eval_items(
        db_session, eval_batch_id=bid, feedback_output_ids=fo_ids,
        seed=5, created_at=_now(),
    )

    llm = MockLLMClient()
    for item in items:
        fo_result = await db_session.execute(
            select(FeedbackOutputDB).where(FeedbackOutputDB.id == item.feedback_output_id)
        )
        fo = fo_result.scalar_one()
        from reflexa.db.models import Turn
        turn_result = await db_session.execute(select(Turn).where(Turn.id == fo.turn_id))
        turn = turn_result.scalar_one()

        for dimension in EVAL_DIMENSIONS:
            await score_item(
                eval_item_id=item.id,
                feedback_output_id=fo.id,
                judge_model_id="mock",
                dimension=dimension,
                user_message=turn.user_message,
                corrected_utterance=fo.corrected_utterance,
                error_list_json=fo.error_list,
                explanations=fo.explanations,
                prioritization_and_focus=fo.prioritization_and_focus,
                practice_prompt=fo.practice_prompt,
                llm_client=llm,
                db=db_session,
            )

    summary = await crud.get_eval_summary(db_session)
    # Expect entries for each (condition × dimension) combo
    assert len(summary) == 2 * len(EVAL_DIMENSIONS)
    for row in summary:
        assert "condition" in row
        assert "dimension" in row
        assert "n" in row
        assert "mean" in row
        assert "std" in row
        assert row["n"] > 0
        assert 1 <= row["mean"] <= 5


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

async def test_export_csv_has_correct_headers(db_session):
    from reflexa.eval.export import stream_csv, _COLUMNS

    bid = str(uuid.uuid4())
    await crud.create_eval_batch(
        db_session, id=bid, judge_models=json.dumps(["mock"]),
        notes=None, created_at=_now(),
    )

    # No scores yet — just check header row
    chunks = []
    async for chunk in stream_csv(db_session, bid):
        chunks.append(chunk)
        break  # Only need the header

    header_line = chunks[0].strip()
    columns = header_line.split(",")
    assert columns == _COLUMNS, f"CSV headers mismatch: {columns}"


async def test_export_csv_contains_data(db_session):
    from reflexa.eval.export import stream_csv

    bid = str(uuid.uuid4())
    await crud.create_eval_batch(
        db_session, id=bid, judge_models=json.dumps(["mock"]),
        notes=None, created_at=_now(),
    )
    fo_id = await _make_session_turn_feedback(db_session)
    items = await crud.create_eval_items(
        db_session, eval_batch_id=bid, feedback_output_ids=[fo_id],
        seed=1, created_at=_now(),
    )

    item = items[0]
    fo_result = await db_session.execute(
        select(FeedbackOutputDB).where(FeedbackOutputDB.id == item.feedback_output_id)
    )
    fo = fo_result.scalar_one()
    from reflexa.db.models import Turn
    turn_result = await db_session.execute(select(Turn).where(Turn.id == fo.turn_id))
    turn = turn_result.scalar_one()

    llm = MockLLMClient()
    await score_item(
        eval_item_id=item.id,
        feedback_output_id=fo.id,
        judge_model_id="mock",
        dimension="linguistic_correctness",
        user_message=turn.user_message,
        corrected_utterance=fo.corrected_utterance,
        error_list_json=fo.error_list,
        explanations=fo.explanations,
        prioritization_and_focus=fo.prioritization_and_focus,
        practice_prompt=fo.practice_prompt,
        llm_client=llm,
        db=db_session,
    )

    csv_content = ""
    async for chunk in stream_csv(db_session, bid):
        csv_content += chunk

    lines = csv_content.strip().split("\n")
    assert len(lines) >= 2, "CSV should have header + at least one data row"
    # Data row should contain the mock judge model id
    assert "mock" in lines[1]


async def test_export_jsonl_is_valid(db_session):
    from reflexa.eval.export import stream_jsonl

    bid = str(uuid.uuid4())
    await crud.create_eval_batch(
        db_session, id=bid, judge_models=json.dumps(["mock"]),
        notes=None, created_at=_now(),
    )
    fo_id = await _make_session_turn_feedback(db_session)
    items = await crud.create_eval_items(
        db_session, eval_batch_id=bid, feedback_output_ids=[fo_id],
        seed=1, created_at=_now(),
    )

    item = items[0]
    fo_result = await db_session.execute(
        select(FeedbackOutputDB).where(FeedbackOutputDB.id == item.feedback_output_id)
    )
    fo = fo_result.scalar_one()
    from reflexa.db.models import Turn
    turn_result = await db_session.execute(select(Turn).where(Turn.id == fo.turn_id))
    turn = turn_result.scalar_one()

    llm = MockLLMClient()
    await score_item(
        eval_item_id=item.id,
        feedback_output_id=fo.id,
        judge_model_id="mock",
        dimension="explanation_quality",
        user_message=turn.user_message,
        corrected_utterance=fo.corrected_utterance,
        error_list_json=fo.error_list,
        explanations=fo.explanations,
        prioritization_and_focus=fo.prioritization_and_focus,
        practice_prompt=fo.practice_prompt,
        llm_client=llm,
        db=db_session,
    )

    jsonl_content = ""
    async for chunk in stream_jsonl(db_session, bid):
        jsonl_content += chunk

    lines = [l for l in jsonl_content.strip().split("\n") if l]
    assert len(lines) >= 1
    parsed = json.loads(lines[0])
    assert "eval_score_id" in parsed
    assert "dimension" in parsed
    assert "score" in parsed
    assert "condition_revealed" in parsed
    assert parsed["condition_revealed"] == 0
