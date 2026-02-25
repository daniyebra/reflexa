"""
Eval harness schemas — Pydantic models for judge output and API I/O.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# LLM judge output (what the judge LLM returns)
# ---------------------------------------------------------------------------

class JudgeOutput(BaseModel):
    score: int = Field(..., ge=1, le=5)
    rationale: str


# ---------------------------------------------------------------------------
# API request / response schemas
# ---------------------------------------------------------------------------

class CreateEvalBatchRequest(BaseModel):
    feedback_output_ids: list[str] | None = None  # null → all unscored
    judge_model_ids: list[str] = Field(default_factory=lambda: ["mock"])
    notes: str | None = None


class CreateEvalBatchResponse(BaseModel):
    eval_batch_id: str
    item_count: int
    status: str


class EvalBatchDetailResponse(BaseModel):
    eval_batch_id: str
    status: str
    judge_models: list[str]
    notes: str | None
    created_at: str
    item_count: int


class EvalScoreRecord(BaseModel):
    eval_score_id: str
    eval_item_id: str
    eval_batch_id: str
    display_order: int
    feedback_output_id: str
    condition: str
    turn_id: str
    judge_model_id: str
    judge_prompt_version_id: str
    dimension: str
    score: int
    rationale: str
    condition_revealed: int
    llm_call_id: str | None
    created_at: str


class EvalBatchResultsResponse(BaseModel):
    eval_batch_id: str
    status: str
    scores: list[EvalScoreRecord]


class DimensionStat(BaseModel):
    condition: str
    dimension: str
    n: int
    mean: float
    std: float


class EvalSummaryResponse(BaseModel):
    stats: list[DimensionStat]


# ---------------------------------------------------------------------------
# Register mock data for JudgeOutput
# ---------------------------------------------------------------------------

def _register_judge_mock() -> None:
    from reflexa.llm.mock import _register
    _register(JudgeOutput, {"score": 3, "rationale": "Mock evaluation rationale."})


_register_judge_mock()
