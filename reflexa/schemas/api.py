from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

class CreateSessionRequest(BaseModel):
    target_language: str = Field(..., min_length=2, max_length=10)
    proficiency_level: str | None = None


class SessionResponse(BaseModel):
    id: str
    target_language: str
    proficiency_level: str | None
    created_at: str
    opener_message: str | None = None


class SessionDetailResponse(BaseModel):
    id: str
    target_language: str
    proficiency_level: str | None
    created_at: str
    turn_count: int


class TurnHistoryItem(BaseModel):
    turn_id: str
    turn_index: int
    user_message: str
    display_condition: str
    created_at: str


class SessionHistoryResponse(BaseModel):
    turns: list[TurnHistoryItem]


# ---------------------------------------------------------------------------
# Chat / Turns
# ---------------------------------------------------------------------------

class CreateTurnRequest(BaseModel):
    user_message: str = Field(..., min_length=1)


class ErrorItemResponse(BaseModel):
    span: str
    description: str
    type: str


class FeedbackResponse(BaseModel):
    turn_id: str
    condition: str
    corrected_utterance: str
    error_list: list[ErrorItemResponse]
    explanations: str
    prioritization_and_focus: str
    practice_prompt: str
    conversation_reply: str
    pipeline_run_id: str
    latency_ms: int


class CreateTurnResponse(BaseModel):
    turn_id: str
    turn_index: int
    feedback: FeedbackResponse


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------

class ArtifactResponse(BaseModel):
    id: str
    pipeline_run_id: str
    condition: str
    stage: str
    stage_index: int
    prompt_version_id: str
    raw_input: str
    raw_output: str
    parsed_output: str | None
    llm_call_id: str | None
    created_at: str


class TurnArtifactsResponse(BaseModel):
    turn_id: str
    artifacts: list[ArtifactResponse]


class FeedbackDetailResponse(BaseModel):
    id: str
    turn_id: str
    condition: str
    corrected_utterance: str
    error_list: str      # raw JSON string
    explanations: str
    prioritization_and_focus: str
    practice_prompt: str
    conversation_reply: str | None = None
    pipeline_run_id: str
    created_at: str
