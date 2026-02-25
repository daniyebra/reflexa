from sqlalchemy import (
    Column, ForeignKey, Index, Integer, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Session(Base):
    __tablename__ = "sessions"

    id = Column(Text, primary_key=True)          # UUID v4
    created_at = Column(Text, nullable=False)    # ISO 8601 UTC
    updated_at = Column(Text, nullable=False)
    target_language = Column(Text, nullable=False)   # ISO 639-1, e.g. "es"
    proficiency_level = Column(Text, nullable=True)  # e.g. "B1"
    metadata_ = Column("metadata", Text, nullable=True)  # JSON blob
    opener_message = Column(Text, nullable=True)

    turns = relationship("Turn", back_populates="session")


class Turn(Base):
    __tablename__ = "turns"
    __table_args__ = (
        Index("ix_turns_session_turn", "session_id", "turn_index"),
    )

    id = Column(Text, primary_key=True)
    session_id = Column(Text, ForeignKey("sessions.id"), nullable=False)
    turn_index = Column(Integer, nullable=False)   # 0-based, monotone per session
    user_message = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False)
    display_condition = Column(Text, nullable=False)  # "baseline" | "corrected"

    session = relationship("Session", back_populates="turns")
    pipeline_runs = relationship("PipelineRun", back_populates="turn")
    feedback_outputs = relationship("FeedbackOutput", back_populates="turn")


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    __table_args__ = (
        UniqueConstraint("turn_id", "condition", name="uq_pipeline_runs_turn_condition"),
    )

    id = Column(Text, primary_key=True)
    turn_id = Column(Text, ForeignKey("turns.id"), nullable=False)
    condition = Column(Text, nullable=False)    # "baseline" | "corrected"
    status = Column(Text, nullable=False)       # "pending"|"running"|"completed"|"failed"
    started_at = Column(Text, nullable=False)
    completed_at = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)

    turn = relationship("Turn", back_populates="pipeline_runs")
    artifacts = relationship("PipelineArtifact", back_populates="pipeline_run")
    feedback_output = relationship("FeedbackOutput", back_populates="pipeline_run", uselist=False)


class FeedbackOutput(Base):
    __tablename__ = "feedback_outputs"
    __table_args__ = (
        UniqueConstraint("turn_id", "condition", name="uq_feedback_outputs_turn_condition"),
    )

    id = Column(Text, primary_key=True)
    turn_id = Column(Text, ForeignKey("turns.id"), nullable=False)
    condition = Column(Text, nullable=False)               # "baseline" | "corrected"
    corrected_utterance = Column(Text, nullable=False)
    error_list = Column(Text, nullable=False)              # JSON array
    explanations = Column(Text, nullable=False)
    prioritization_and_focus = Column(Text, nullable=False)
    practice_prompt = Column(Text, nullable=False)
    conversation_reply = Column(Text, nullable=True)  # nullable for existing rows
    pipeline_run_id = Column(Text, ForeignKey("pipeline_runs.id"), nullable=False)
    created_at = Column(Text, nullable=False)

    turn = relationship("Turn", back_populates="feedback_outputs")
    pipeline_run = relationship("PipelineRun", back_populates="feedback_output")
    eval_items = relationship("EvalItem", back_populates="feedback_output")


class LLMCall(Base):
    __tablename__ = "llm_calls"

    id = Column(Text, primary_key=True)
    model_id = Column(Text, nullable=False)           # e.g. "gpt-4o"
    prompt_version_id = Column(Text, nullable=False)  # e.g. "baseline/v1"
    caller_context = Column(Text, nullable=False)     # e.g. "pipeline/baseline"
    tokens_in = Column(Integer, nullable=True)
    tokens_out = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    retries = Column(Integer, nullable=False, default=0)
    estimated_cost_usd = Column(Text, nullable=True)  # stored as REAL via Text for SQLite compat
    error = Column(Text, nullable=True)               # null on success
    created_at = Column(Text, nullable=False)

    artifacts = relationship("PipelineArtifact", back_populates="llm_call")
    eval_scores = relationship("EvalScore", back_populates="llm_call")


class PipelineArtifact(Base):
    __tablename__ = "pipeline_artifacts"

    id = Column(Text, primary_key=True)
    pipeline_run_id = Column(Text, ForeignKey("pipeline_runs.id"), nullable=False)
    stage = Column(Text, nullable=False)          # "baseline"|"draft"|"verifier"|"critic"|"reviser"
    stage_index = Column(Integer, nullable=False)
    prompt_version_id = Column(Text, nullable=False)  # e.g. "pipeline_draft/v1"
    raw_input = Column(Text, nullable=False)           # JSON: messages array sent to LLM
    raw_output = Column(Text, nullable=False)          # raw LLM response string
    parsed_output = Column(Text, nullable=True)        # JSON of parsed Pydantic model; null if failed
    llm_call_id = Column(Text, ForeignKey("llm_calls.id"), nullable=True)
    created_at = Column(Text, nullable=False)

    pipeline_run = relationship("PipelineRun", back_populates="artifacts")
    llm_call = relationship("LLMCall", back_populates="artifacts")


class EvalBatch(Base):
    __tablename__ = "eval_batches"

    id = Column(Text, primary_key=True)
    created_at = Column(Text, nullable=False)
    notes = Column(Text, nullable=True)          # human annotation + random seed
    judge_models = Column(Text, nullable=False)  # JSON array of model ID strings
    status = Column(Text, nullable=False, default="queued")  # "queued"|"running"|"completed"|"failed"

    items = relationship("EvalItem", back_populates="eval_batch")


class EvalItem(Base):
    __tablename__ = "eval_items"

    id = Column(Text, primary_key=True)
    feedback_output_id = Column(Text, ForeignKey("feedback_outputs.id"), nullable=False)
    eval_batch_id = Column(Text, ForeignKey("eval_batches.id"), nullable=False)
    display_order = Column(Integer, nullable=False)   # randomized per batch (blinding)
    created_at = Column(Text, nullable=False)

    feedback_output = relationship("FeedbackOutput", back_populates="eval_items")
    eval_batch = relationship("EvalBatch", back_populates="items")
    scores = relationship("EvalScore", back_populates="eval_item")


class EvalScore(Base):
    __tablename__ = "eval_scores"
    __table_args__ = (
        UniqueConstraint(
            "eval_item_id", "judge_model_id", "dimension",
            name="uq_eval_scores_item_judge_dimension",
        ),
    )

    id = Column(Text, primary_key=True)
    eval_item_id = Column(Text, ForeignKey("eval_items.id"), nullable=False)
    judge_model_id = Column(Text, nullable=False)
    judge_prompt_version_id = Column(Text, nullable=False)
    dimension = Column(Text, nullable=False)          # one of 5 axes
    score = Column(Integer, nullable=False)           # 1–5
    rationale = Column(Text, nullable=False)
    condition_revealed = Column(Integer, nullable=False, default=0)  # 0=blinded
    llm_call_id = Column(Text, ForeignKey("llm_calls.id"), nullable=True)
    created_at = Column(Text, nullable=False)

    eval_item = relationship("EvalItem", back_populates="scores")
    llm_call = relationship("LLMCall", back_populates="eval_scores")
