# Reflexa: Product Requirements Document

> **Version**: 1.0 | **Date**: 2026-02-24 | **Status**: Draft

---

## Table of Contents
1. Problem Statement & Goals
2. Non-Goals
3. User Stories
4. System Architecture
5. Data Model (SQLite)
6. API Design
7. Prompting Strategy & Versioning
8. Pipeline Specifications
9. UI Requirements
10. Evaluation Harness
11. Observability & Telemetry
12. Security & Privacy
13. Milestones & Acceptance Criteria
14. Risks & Mitigations
15. Definition of Done

---

## 1. Problem Statement & Goals

### Problem
Language learners receive feedback of inconsistent quality from LLM-based tutors. A single-pass generation approach (Baseline) may miss errors, hallucinate corrections, or produce pedagogically unhelpful explanations. A multi-stage self-correction pipeline (Corrected) — where the baseline output is reviewed by a linguistic verifier and a pedagogical critic, then revised — may produce higher-quality feedback, but this hypothesis has not been empirically validated.

### Goals
- **G1**: Build a research platform that captures structured corrective feedback for learner messages in a target language.
- **G2**: Run two generation conditions for every user turn — Baseline first, then Corrected as a refinement of the Baseline output — store all outputs and intermediate artifacts, and expose them for offline evaluation.
- **G3**: Implement an offline LLM-judge evaluation harness that scores each output on five axes with full blinding and reproducibility.
- **G4**: Produce a system that is end-to-end functional within two weeks, with a mock LLM fallback for API-key-free development.
- **G5**: Keep the system simple, local, and self-contained (SQLite, no cloud infra required).

---

## 2. Non-Goals
- **NG1**: Real-time streaming of feedback (batch response is acceptable).
- **NG2**: Multi-user concurrency at scale (SQLite + single process is sufficient for research).
- **NG3**: Authentication or authorization (single-researcher tool; no user accounts).
- **NG4**: Production deployment or containerization (local development machine only in v1).
- **NG5**: Supporting languages other than Spanish in Phase 0–3 (architecture is language-agnostic, but prompts default to Spanish).
- **NG6**: A/B testing visible to the user (only one condition shown; the other is latent).
- **NG7**: Automatic model fine-tuning from eval scores.

---

## 3. User Stories

| ID | As a… | I want to… | So that… |
|----|-------|------------|----------|
| US-01 | Researcher | Start a new chat session with a target language | I can begin collecting learner turn data |
| US-02 | Learner (simulated) | Write a message in Spanish and receive corrective feedback | I can see what the system produces |
| US-03 | Researcher | Have both Baseline and Corrected outputs stored silently | I can compare conditions offline |
| US-04 | Researcher | Inspect all intermediate pipeline artifacts for any turn | I can trace how the final output was generated |
| US-05 | Researcher | Run an offline evaluation over all stored outputs | I can score quality with multiple LLM judges |
| US-06 | Researcher | Export evaluation scores as CSV or JSONL | I can analyze results in Python/R |
| US-07 | Researcher | Use the system without an OpenAI API key | I can develop and test locally |
| US-08 | Researcher | See latency and token cost for every LLM call | I can monitor and control API spend |

---

## 4. System Architecture

### 4.1 Component Overview

```
┌─────────────────────────────────────────────────────────┐
│                     Streamlit UI (ui/app.py)            │
│   Language selector → Chat input → Feedback display     │
└────────────────────────────┬────────────────────────────┘
                             │ HTTP (localhost)
┌────────────────────────────▼────────────────────────────┐
│                   FastAPI Backend (reflexa/api/)         │
│  /sessions   /turns   /artifacts   /eval                │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │           Pipeline Orchestrator                 │   │
│  │                                                 │   │
│  │  ┌──────────────┐                              │   │
│  │  │  Baseline    │  → FeedbackOutput (display)  │   │
│  │  │  (1 LLM call)│        │                     │   │
│  │  └──────────────┘        │ (passed as draft)   │   │
│  │                          ▼                     │   │
│  │  ┌────────────────────────────────────────┐   │   │
│  │  │  Corrected (3-stage, background)       │   │   │
│  │  │  Verify + Critic → Revise              │   │   │
│  │  └────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  ┌──────────────────────────────────────────────────┐  │
│  │           Unified LLM Client Wrapper              │  │
│  │   (telemetry, retries, mock fallback, cost est.) │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────────┬────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────┐
│                  SQLite Database (reflexa.db)            │
│  sessions / turns / feedback_outputs / pipeline_runs    │
│  pipeline_artifacts / llm_calls / eval_batches          │
│  eval_items / eval_scores                               │
└─────────────────────────────────────────────────────────┘
                             ↑
┌────────────────────────────┴────────────────────────────┐
│          Offline Evaluation Harness (eval/)             │
│   Blinded judge scoring → eval_scores storage → export  │
└─────────────────────────────────────────────────────────┘
```

### 4.2 Directory Structure

```
reflexa/                          # repo root
├── pyproject.toml                # PEP 517/518, all deps pinned
├── .env.example                  # env var template
├── .gitignore
├── README.md
├── Makefile                      # dev / test / eval / export targets
├── prd.md                        # this document
│
├── reflexa/                      # main Python package
│   ├── __init__.py
│   ├── config.py                 # pydantic-settings; single source of truth
│   │
│   ├── db/
│   │   ├── engine.py             # async engine, session factory, get_db()
│   │   ├── models.py             # SQLAlchemy ORM (all 9 tables)
│   │   └── crud.py               # all DB read/write helpers
│   │
│   ├── schemas/
│   │   ├── feedback.py           # FeedbackOutput, ErrorItem (core output schema)
│   │   ├── api.py                # FastAPI request/response schemas
│   │   └── eval.py               # eval endpoint schemas
│   │
│   ├── llm/
│   │   ├── client.py             # LLMClient (telemetry, retries, structured output)
│   │   ├── mock.py               # MockLLMClient (no API key needed)
│   │   └── cost.py               # per-model token cost table
│   │
│   ├── prompts/                  # versioned YAML prompt files (never edited in place)
│   │   ├── baseline/v1.yaml
│   │   ├── pipeline_draft/v1.yaml
│   │   ├── pipeline_verifier/v1.yaml
│   │   ├── pipeline_critic/v1.yaml
│   │   ├── pipeline_reviser/v1.yaml
│   │   └── eval_judge/v1.yaml
│   │
│   ├── prompt_loader.py          # loads/caches YAML prompts, version resolution
│   ├── memory.py                 # ConversationMemory (last-N-turns bounded history)
│   │
│   ├── pipeline/
│   │   ├── baseline.py           # run_baseline() coroutine
│   │   ├── corrected.py          # run_corrected() 4-stage coroutine
│   │   └── orchestrator.py       # run_both_conditions() + PipelineContext
│   │
│   ├── api/
│   │   ├── main.py               # FastAPI app factory, lifespan, router registration
│   │   ├── deps.py               # dependency injection (get_db, get_llm_client)
│   │   ├── middleware.py          # request ID injection, CORS
│   │   └── routers/
│   │       ├── sessions.py
│   │       ├── chat.py
│   │       ├── artifacts.py
│   │       └── eval.py
│   │
│   └── eval/
│       ├── harness.py            # run_evaluation() orchestrator
│       ├── judge.py              # single LLM judge call
│       └── export.py             # CSV/JSONL streaming export
│
├── ui/
│   └── app.py                    # Streamlit frontend
│
├── scripts/
│   ├── init_db.py                # one-time schema creation
│   ├── run_eval.py               # CLI for offline evaluation
│   └── export_results.py         # CLI for export
│
└── tests/
    ├── conftest.py               # in-memory SQLite fixture, mock LLM fixture
    ├── test_llm_client.py
    ├── test_api.py
    ├── test_eval_harness.py
    └── test_prompt_loader.py
```

---

## 5. Data Model (SQLite)

All tables use UUID v4 TEXT primary keys. All timestamps are ISO 8601 UTC TEXT. `PRAGMA foreign_keys = ON` and `PRAGMA journal_mode = WAL` are set at engine startup.

### 5.1 `sessions`
```sql
CREATE TABLE sessions (
  id                TEXT PRIMARY KEY,   -- UUID v4
  created_at        TEXT NOT NULL,      -- ISO 8601 UTC
  updated_at        TEXT NOT NULL,
  target_language   TEXT NOT NULL,      -- ISO 639-1, e.g. "es"
  proficiency_level TEXT,               -- e.g. "B1", nullable
  metadata          TEXT                -- JSON blob
);
```

### 5.2 `turns`
```sql
CREATE TABLE turns (
  id                TEXT PRIMARY KEY,
  session_id        TEXT NOT NULL REFERENCES sessions(id),
  turn_index        INTEGER NOT NULL,   -- 0-based, monotone per session
  user_message      TEXT NOT NULL,
  created_at        TEXT NOT NULL,
  display_condition TEXT NOT NULL       -- "baseline" | "corrected"
);
-- Index: (session_id, turn_index)
```

### 5.3 `pipeline_runs`
```sql
CREATE TABLE pipeline_runs (
  id            TEXT PRIMARY KEY,
  turn_id       TEXT NOT NULL REFERENCES turns(id),
  condition     TEXT NOT NULL,          -- "baseline" | "corrected"
  status        TEXT NOT NULL,          -- "pending" | "running" | "completed" | "failed"
  started_at    TEXT NOT NULL,
  completed_at  TEXT,
  error_message TEXT
  -- UNIQUE (turn_id, condition)
);
```

### 5.4 `feedback_outputs`
```sql
CREATE TABLE feedback_outputs (
  id                       TEXT PRIMARY KEY,
  turn_id                  TEXT NOT NULL REFERENCES turns(id),
  condition                TEXT NOT NULL,   -- "baseline" | "corrected"
  corrected_utterance      TEXT NOT NULL,
  error_list               TEXT NOT NULL,   -- JSON array: [{span, description, type}]
  explanations             TEXT NOT NULL,
  prioritization_and_focus TEXT NOT NULL,
  practice_prompt          TEXT NOT NULL,
  pipeline_run_id          TEXT NOT NULL REFERENCES pipeline_runs(id),
  created_at               TEXT NOT NULL
  -- UNIQUE (turn_id, condition)
);
```

### 5.5 `pipeline_artifacts`
```sql
CREATE TABLE pipeline_artifacts (
  id                TEXT PRIMARY KEY,
  pipeline_run_id   TEXT NOT NULL REFERENCES pipeline_runs(id),
  stage             TEXT NOT NULL,   -- "baseline" | "draft" | "verifier" | "critic" | "reviser"
  stage_index       INTEGER NOT NULL,
  prompt_version_id TEXT NOT NULL,   -- e.g. "pipeline_draft/v1"
  raw_input         TEXT NOT NULL,   -- JSON: messages array sent to LLM
  raw_output        TEXT NOT NULL,   -- raw LLM response string
  parsed_output     TEXT,            -- JSON of parsed Pydantic model; null if parse failed
  llm_call_id       TEXT REFERENCES llm_calls(id),
  created_at        TEXT NOT NULL
);
```

### 5.6 `llm_calls`
```sql
CREATE TABLE llm_calls (
  id                  TEXT PRIMARY KEY,
  model_id            TEXT NOT NULL,      -- e.g. "gpt-4o"
  prompt_version_id   TEXT NOT NULL,      -- e.g. "baseline/v1"
  caller_context      TEXT NOT NULL,      -- e.g. "pipeline/baseline", "eval/judge"
  tokens_in           INTEGER,
  tokens_out          INTEGER,
  latency_ms          INTEGER,
  retries             INTEGER NOT NULL DEFAULT 0,
  estimated_cost_usd  REAL,
  error               TEXT,               -- null on success
  created_at          TEXT NOT NULL
);
```

### 5.7 `eval_batches`
```sql
CREATE TABLE eval_batches (
  id           TEXT PRIMARY KEY,
  created_at   TEXT NOT NULL,
  notes        TEXT,                 -- human annotation, also stores random seed
  judge_models TEXT NOT NULL,        -- JSON array of model ID strings
  status       TEXT NOT NULL DEFAULT "queued"  -- "queued"|"running"|"completed"|"failed"
);
```

### 5.8 `eval_items`
```sql
CREATE TABLE eval_items (
  id                 TEXT PRIMARY KEY,
  feedback_output_id TEXT NOT NULL REFERENCES feedback_outputs(id),
  eval_batch_id      TEXT NOT NULL REFERENCES eval_batches(id),
  display_order      INTEGER NOT NULL,   -- randomized per batch (blinding)
  created_at         TEXT NOT NULL
);
```

### 5.9 `eval_scores`
```sql
CREATE TABLE eval_scores (
  id                      TEXT PRIMARY KEY,
  eval_item_id            TEXT NOT NULL REFERENCES eval_items(id),
  judge_model_id          TEXT NOT NULL,
  judge_prompt_version_id TEXT NOT NULL,
  dimension               TEXT NOT NULL,    -- one of 5 axes (see §10)
  score                   INTEGER NOT NULL, -- 1-5
  rationale               TEXT NOT NULL,
  condition_revealed      INTEGER NOT NULL DEFAULT 0,   -- 0=blinded
  llm_call_id             TEXT REFERENCES llm_calls(id),
  created_at              TEXT NOT NULL
  -- UNIQUE (eval_item_id, judge_model_id, dimension)
);
```

### 5.10 Entity Relationship Summary
```
sessions ──1:N──► turns ──1:N──► pipeline_runs ──1:N──► pipeline_artifacts ──1:1──► llm_calls
                        └──1:N──► feedback_outputs ──1:N──► eval_items ──N:1──► eval_batches
                                                                       └──1:N──► eval_scores ──1:1──► llm_calls
```

---

## 6. API Design

Base URL: `http://localhost:8000`. All requests/responses are JSON. Error format: `{"detail": {"code": "...", "message": "...", "field": "..."}}` (RFC 7807).

### 6.1 Sessions

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/sessions` | Create new anonymous session |
| `GET` | `/sessions/{session_id}` | Session metadata + turn count |
| `GET` | `/sessions/{session_id}/history` | Last N turns (bounded by MEMORY_TURNS) |

**POST /sessions** — Request:
```json
{ "target_language": "es", "proficiency_level": "B1" }
```
Response `201`:
```json
{ "id": "<uuid>", "target_language": "es", "proficiency_level": "B1", "created_at": "..." }
```

### 6.2 Chat

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/sessions/{session_id}/turns` | Submit user message; returns display-condition feedback |

**POST /sessions/{session_id}/turns** — Request:
```json
{ "user_message": "Yo fui al mercado ayer y compré muchos vegetables." }
```
Response `201`:
```json
{
  "turn_id": "<uuid>",
  "turn_index": 0,
  "feedback": {
    "turn_id": "<uuid>",
    "condition": "baseline",
    "corrected_utterance": "Fui al mercado ayer y compré muchas verduras.",
    "error_list": [
      { "span": "Yo fui", "description": "Redundant subject pronoun in Spanish", "type": "grammar" },
      { "span": "vegetables", "description": "English word used; use 'verduras'", "type": "vocabulary" }
    ],
    "explanations": "...",
    "prioritization_and_focus": "...",
    "practice_prompt": "...",
    "pipeline_run_id": "<uuid>",
    "latency_ms": 1243
  }
}
```

Implementation: always awaits baseline first; if `display_condition="baseline"`, returns immediately and fires the corrected pipeline as a background task using the baseline output as draft. If `display_condition="corrected"`, awaits corrected sequentially after baseline.

### 6.3 Artifacts

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/turns/{turn_id}/artifacts` | All pipeline artifacts for a turn (both conditions) |
| `GET` | `/turns/{turn_id}/feedback/{condition}` | Structured output for a specific condition |

### 6.4 Evaluation

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/eval/batches` | Create and queue an evaluation batch |
| `GET` | `/eval/batches/{batch_id}` | Batch status + progress |
| `GET` | `/eval/batches/{batch_id}/results` | All scores for a batch |
| `GET` | `/eval/batches/{batch_id}/export` | Download CSV or JSONL (`?format=csv\|jsonl`) |
| `GET` | `/eval/summary` | Aggregate mean/std per condition × dimension |
| `GET` | `/health` | DB + LLM connectivity check |

**POST /eval/batches** — Request:
```json
{
  "feedback_output_ids": null,
  "judge_model_ids": ["gpt-4o-mini", "gpt-4o"],
  "notes": "Run 1 — post Phase 2"
}
```
Response `202`:
```json
{ "eval_batch_id": "<uuid>", "item_count": 42, "status": "queued" }
```

---

## 7. Prompting Strategy & Versioning

### 7.1 File Format

Every prompt lives at `reflexa/prompts/{name}/v{N}.yaml`. Files are **immutable once committed** — edits require a new `v{N+1}.yaml`.

```yaml
# reflexa/prompts/baseline/v1.yaml
version_id: "baseline/v1"
description: "Single-call baseline feedback prompt"
created_at: "2026-02-24"
model_constraints:
  temperature: 0.3
  max_tokens: 1024
system: |
  You are an expert language teacher specializing in {target_language}.
  The student is at {proficiency_level} level.
  Analyze the student's message for linguistic errors and return ONLY a JSON object
  matching this schema exactly:
  {
    "corrected_utterance": str,
    "error_list": [{"span": str, "description": str, "type": str}],
    "explanations": str,
    "prioritization_and_focus": str,
    "practice_prompt": str
  }
user_template: |
  Student message: {user_message}

  Conversation context:
  {conversation_history}
```

### 7.2 PromptLoader

`reflexa/prompt_loader.py` — module-level singleton initialized at app startup:
- Scans all `reflexa/prompts/**/*.yaml` at import time.
- `get(version_id: str) -> PromptTemplate`
- `latest(name: str) -> PromptTemplate` — highest `vN` for that name.
- Active version per stage configurable via env vars (e.g. `BASELINE_PROMPT_VERSION=baseline/v1`); defaults to `latest`.

### 7.3 Versioning Rules
1. YAML files never modified after first commit.
2. All changes increment the version number.
3. `prompt_version_id` stored in every `llm_calls` row and `pipeline_artifacts` row — sufficient to reconstruct the exact prompt used for any historical call.
4. Git history of `reflexa/prompts/` provides the audit trail.

### 7.4 Prompt Overview by Stage

| Stage | File | Output Schema |
|-------|------|---------------|
| Baseline | `baseline/v{N}.yaml` | `FeedbackOutput` |
| Verifier | `pipeline_verifier/v1.yaml` | `{"issues": [...], "missed_errors": [...], "verdict": "pass"\|"revise"}` |
| Critic | `pipeline_critic/v1.yaml` | `{"critique": [...], "suggestions": [...], "verdict": "pass"\|"revise"}` |
| Reviser | `pipeline_reviser/v{N}.yaml` | `FeedbackOutput` |
| Eval Judge | `eval_judge/v1.yaml` | `{"score": 1-5, "rationale": str}` |

Note: `pipeline_draft/v1.yaml` exists in the repository for historical reference but is no longer called at runtime. The baseline output serves as the draft input to the corrected pipeline.

---

## 8. Pipeline Specifications

### 8.1 Core Data Schema (`reflexa/schemas/feedback.py`)

```python
class ErrorItem(BaseModel):
    span: str           # quoted substring from the original message
    description: str    # brief error explanation
    type: str           # "grammar" | "vocabulary" | "spelling" | "syntax" | "other"

class FeedbackOutput(BaseModel):
    corrected_utterance:      str
    error_list:               list[ErrorItem]
    explanations:             str
    prioritization_and_focus: str
    practice_prompt:          str
```

### 8.2 Shared Context Dataclass

```python
@dataclass
class PipelineContext:
    turn_id:              str
    session_id:           str
    user_message:         str
    target_language:      str
    proficiency_level:    str | None
    conversation_history: list[dict]   # pre-truncated to MEMORY_TURNS
    db:                   AsyncSession
    llm_client:           LLMClient
```

### 8.3 Condition A — Baseline Pipeline

```
user_message + history → [LLM: baseline/v1] → FeedbackOutput
```

Steps:
1. Create `pipeline_runs` row (`status="running"`).
2. Load `baseline/v1` prompt; render with context.
3. Call `llm_client.complete(response_model=FeedbackOutput)`.
4. Write `pipeline_artifacts` row (stage="baseline", stage_index=0).
5. Write `feedback_outputs` row.
6. Update `pipeline_runs` to `status="completed"`.

### 8.4 Condition B — Corrected Pipeline (3 Active Stages + Baseline Passthrough)

```
baseline FeedbackOutput (passthrough) ─┬──── verifier/v1 ────┐
                                        │                      ├── reviser/v{N} → FeedbackOutput
                                        └──── critic/v1 ───────┘
```

The corrected pipeline does **not** make an independent draft LLM call. It takes the Baseline `FeedbackOutput` as its starting point (recorded as a "draft" artifact with `prompt_version_id="baseline_passthrough/v1"`) and applies three stages to improve it:

- **Stage 0 (Draft — passthrough)**: Baseline output stored as artifact; no LLM call.
- **Stage 1 (Verifier)** and **Stage 2 (Critic)**: Run in **parallel** (`asyncio.gather`) — both receive the baseline output as input. Independent of each other.
  - Verifier: checks linguistic accuracy, missed errors, hallucinations.
  - Critic: checks pedagogical clarity, level-appropriateness, actionability.
- **Stage 3 (Reviser)**: Receives baseline output + verifier report + critic report → produces final `FeedbackOutput`.

All 4 artifact rows are written (passthrough draft + verifier + critic + reviser). Total: 4 artifacts per corrected run.

This design ensures the evaluation directly measures the improvement attributable to the correction pipeline: **Corrected = Baseline + (Verifier + Critic + Reviser)**.

### 8.5 Orchestrator

Baseline always runs first. Its output is passed as the draft to the corrected pipeline.

```python
async def run_both_conditions(ctx, display_condition) -> PipelineResult:
    # Step 1: always await baseline (provides the draft for the corrected pipeline)
    baseline_result = await run_baseline(ctx)

    if display_condition == "baseline":
        # Return baseline immediately; fire corrected in background
        asyncio.create_task(
            _run_corrected_background(ctx, baseline_result.feedback)
        )
        return baseline_result
    else:
        # Await corrected (which uses baseline output as draft) and return it
        return await run_corrected(ctx, baseline_feedback=baseline_result.feedback)
```

The route handler returns the HTTP response as soon as the display condition result is available. When `display_condition="baseline"` (the default), the corrected pipeline runs as a background task after the response is sent.

### 8.6 Conversation Memory

`reflexa/memory.py` — `ConversationMemory(max_turns=N)`:
- Fetches last N turns from DB (`crud.get_recent_turns`).
- Returns `[{"role": "user", "content": msg}, {"role": "assistant", "content": corrected_utterance}, ...]`.
- Only the display-condition's corrected utterance is used in history (prevents contamination).

---

## 9. UI Requirements

### 9.1 Streamlit App (`ui/app.py`)

**Session initialization** (on first load):
- Sidebar: language selector (dropdown: Spanish, French, Portuguese, Italian, German) and proficiency selector (A1–C2).
- "Start Session" button → calls `POST /sessions` → stores `session_id` in `st.session_state`.

**Chat loop**:
- `st.chat_input` for user message.
- On submit → `POST /sessions/{session_id}/turns` → display feedback.

**Feedback display** (structured, not raw JSON):
- **Corrected utterance**: shown prominently, highlighted diffs optional.
- **Error list**: table or bullet list with span / type / description columns.
- **Explanations**: paragraph block.
- **Prioritization & Focus**: callout box.
- **Practice prompt**: card with distinct styling.

**Sidebar info**:
- Session ID (anonymized display: first 8 chars).
- Turn count.
- "Condition shown: Baseline" (static label; no toggle).
- Last turn latency (ms).

**Constraints**:
- No condition toggle in the UI.
- Session persists across page refreshes via `st.session_state`.
- Works with `OPENAI_API_KEY=mock` (mock client).

---

## 10. Evaluation Harness

### 10.1 Scoring Dimensions (5 axes, 1–5 scale)

| Dimension | Description |
|-----------|-------------|
| `linguistic_correctness` | Are corrections accurate? No spurious or wrong corrections? |
| `explanation_quality` | Are explanations clear, specific, tied to each error? |
| `actionability` | Is the practice prompt useful and targeted? |
| `level_appropriateness` | Is complexity matched to learner's proficiency level? |
| `prioritization_and_focus` | Are the most important errors correctly prioritized? |

### 10.2 Blinding Mechanism
- `feedback_output.condition` is **never** included in the judge prompt context.
- Items within a batch are shuffled with a logged random seed (stored in `eval_batches.notes`).
- `eval_scores.condition_revealed = 0` always in v1.
- Post-analysis: join `eval_scores` → `eval_items` → `feedback_outputs` to reveal condition.

### 10.3 Harness Flow

```
POST /eval/batches
  │
  ▼ (background asyncio.Task)
harness.run_evaluation(eval_batch_id)
  │
  ├── fetch all eval_items (randomized display_order)
  │
  └── for each (item × judge_model × dimension):
        judge.score_item(...)
          │
          ├── render judge prompt (blinded: no condition field)
          ├── llm_client.complete(response_model=JudgeOutput)
          └── crud.create_eval_score(...)
  │
  └── mark eval_batch status="completed"
```

Bounded concurrency: `asyncio.Semaphore(10)` prevents rate-limit bursts.

### 10.4 Export Columns (CSV/JSONL)

```
eval_score_id, eval_item_id, eval_batch_id, display_order,
feedback_output_id, condition, turn_id, session_id,
target_language, proficiency_level, user_message,
corrected_utterance, error_list_json, explanations,
prioritization_and_focus, practice_prompt,
judge_model_id, judge_prompt_version_id,
dimension, score, rationale, condition_revealed,
llm_call_id, created_at
```

Streamed via `StreamingResponse` (no full in-memory load).

### 10.5 Dataset Creation
- Every turn generates two `feedback_outputs` rows: Baseline (from single LLM call) and Corrected (Baseline refined by verifier + critic + reviser). The Corrected output is always derived from the Baseline of the same turn.
- Turns where the learner made no errors (`error_list = []`) are excluded from eval batches — there is nothing to improve, so comparison is not meaningful.
- Any `feedback_output` row with errors can be included in an eval batch; pass specific `feedback_output_ids` or `null` for all unscored.
- Recommended: collect ≥ 50 turns with errors before running evaluation for statistical power.

---

## 11. Observability & Telemetry

### 11.1 LLM Call Telemetry
Every LLM call writes one `llm_calls` row containing:
- `model_id`, `prompt_version_id`, `caller_context`
- `tokens_in`, `tokens_out`, `latency_ms`, `retries`, `estimated_cost_usd`, `error`

### 11.2 Request Logging
`reflexa/api/middleware.py`:
- Injects `X-Request-ID` header (UUID) into every request.
- Logs: `method`, `path`, `status_code`, `duration_ms`, `request_id` on every response.

### 11.3 Structured Logging
Use Python `logging` module with a structured formatter. Key loggers:
- `reflexa.pipeline`: per-stage timing, success/failure.
- `reflexa.llm`: per-call telemetry (mirrors `llm_calls` table).
- `reflexa.eval`: batch start/end, item counts.
- `reflexa.api`: request/response (from middleware).

Log level configurable via `LOG_LEVEL` env var (default: `INFO`).

### 11.4 Health Endpoint
`GET /health` returns:
```json
{ "status": "ok", "db": "ok", "llm": "mock" | "live" }
```
Returns `503` if DB is unreachable.

### 11.5 Cost Monitoring
`GET /eval/summary` includes aggregate `estimated_cost_usd` across all `llm_calls` for the session/batch. CLI `scripts/run_eval.py --dry-run` prints estimated cost without making calls.

---

## 12. Security & Privacy

### 12.1 Session Anonymization
- Session IDs are UUID v4 generated server-side; no linkage to real-user identity.
- No PII is collected. User messages are stored as-is; researchers are responsible for not entering real personal data.

### 12.2 API Key Handling
- `OPENAI_API_KEY` loaded exclusively from environment variable or `.env` file (never hardcoded).
- `.env` is in `.gitignore`.
- `.env.example` provides the template with placeholder values.

### 12.3 Data Retention
- `reflexa.db` is a local SQLite file. Retention is managed by the researcher (delete the file to purge all data).
- No data is transmitted except to the configured LLM API endpoint.

### 12.4 Input Validation
- All API inputs validated by Pydantic v2 with `strict=True`.
- `user_message` length capped at 2000 characters (configurable via `MAX_MESSAGE_LENGTH` env var).
- SQL injection is not possible via SQLAlchemy ORM with parameterized queries.

### 12.5 CORS
- Restricted to `localhost` origins in `middleware.py`. Not exposed to the internet.

---

## 13. Milestones & Acceptance Criteria

### Phase 0 — Scaffolding & Database (Days 1–2)
**Goal**: Working skeleton with all tables, no LLM calls yet.

Tasks:
- `pyproject.toml` with pinned deps: `fastapi`, `sqlalchemy[asyncio]`, `aiosqlite`, `pydantic[email]>=2`, `openai`, `instructor`, `pydantic-settings`, `pyyaml`, `uvicorn`, `streamlit`, `httpx`, `pytest`, `pytest-asyncio`.
- `reflexa/config.py` (all env vars).
- `reflexa/db/engine.py` (async engine, WAL pragma, FK pragma, `get_db()`).
- `reflexa/db/models.py` (all 9 tables).
- `scripts/init_db.py`.
- `reflexa/db/crud.py` (stub functions with `raise NotImplementedError`).
- `tests/conftest.py` (in-memory SQLite fixture).

**Acceptance**:
- `python scripts/init_db.py` creates `reflexa.db` with all 9 tables (verified via `sqlite3 reflexa.db .tables`).
- `pytest tests/` exits 0 (stubs have no assertions yet).

### Phase 1 — LLM Client & Prompt Loader (Days 3–4)
**Goal**: Fully tested LLM wrapper with mock fallback and versioned prompt loading.

Tasks:
- `reflexa/llm/cost.py`, `reflexa/llm/mock.py`, `reflexa/llm/client.py`.
- `reflexa/prompt_loader.py`.
- All 6 prompt YAML files (`v1`).
- `crud.create_llm_call()` implemented.

**Acceptance**:
- `MockLLMClient.complete()` returns valid `FeedbackOutput` and inserts `llm_calls` row.
- `LLMClient` with real API key makes successful structured call via `instructor`.
- `PromptLoader.latest("baseline").version_id == "baseline/v1"`.
- `tests/test_llm_client.py` passes: mock call, retry on transient failure, cost estimation.
- `tests/test_prompt_loader.py` passes: version resolution, YAML field presence.

### Phase 2 — Pipeline & API Core (Days 5–7)
**Goal**: Full pipeline end-to-end; chat endpoint returns feedback; all artifacts stored.

Tasks:
- `reflexa/memory.py`.
- `reflexa/pipeline/baseline.py`, `corrected.py`, `orchestrator.py`.
- All `crud.py` functions needed by pipelines.
- `reflexa/api/deps.py`, `main.py`, all 3 routers (sessions, chat, artifacts).

**Acceptance**:
- `POST /sessions` creates session row.
- `POST /sessions/{id}/turns` returns valid `CreateTurnResponse`.
- After response: both `pipeline_run` rows exist (`status="completed"`); corrected has 4 artifacts, baseline has 1.
- `GET /turns/{id}/artifacts` returns 5 artifact records.
- `tests/test_api.py` and `tests/test_pipeline.py` pass with mock LLM.

### Phase 3 — Streamlit UI (Days 8–9)
**Goal**: Usable chat interface.

Tasks: `ui/app.py` (language selector, session creation, chat loop, structured feedback display).

**Acceptance**:
- `streamlit run ui/app.py` launches without error.
- Full chat loop works with mock LLM (no API key).
- Session ID persists across page refresh.
- Feedback displayed in structured format (not raw JSON).

### Phase 4 — Evaluation Harness (Days 10–12)
**Goal**: Full offline evaluation pipeline with export.

Tasks:
- `reflexa/eval/judge.py`, `harness.py`, `export.py`.
- `reflexa/api/routers/eval.py` + crud functions for eval tables.
- `scripts/run_eval.py`, `scripts/export_results.py`.

**Acceptance**:
- `POST /eval/batches` with mock judges produces scores for all (item × dimension × judge) combinations.
- `eval_scores.condition_revealed == 0` for all rows.
- `display_order` values form a permutation of 1..N.
- `GET /eval/batches/{id}/export?format=csv` returns valid CSV with correct headers.
- `GET /eval/summary` returns per-condition × per-dimension mean and std.
- `tests/test_eval_harness.py` passes: blinding (condition not in judge input), randomization, score storage.

### Phase 5 — Hardening (Days 13–14)
**Goal**: Research-grade robustness, full documentation.

Tasks:
- `asyncio.timeout()` on all LLM calls (default 30s, configurable).
- Structured logging + middleware (request ID, timing).
- `GET /health` endpoint.
- `README.md`: setup, env vars, run-eval instructions.
- `Makefile`: `make dev`, `make test`, `make eval`, `make export`.
- Graceful pipeline failure (background task failure doesn't affect displayed result).
- Pydantic 422 handler.

**Acceptance**:
- `GET /health` returns `200 {"status": "ok", "db": "ok", "llm": ...}`.
- Simulated 35s LLM timeout → `LLMCallError` logged; no 500 returned to UI.
- `pytest tests/ -v` passes; ≥80% line coverage.
- New contributor can run the system from scratch in ≤10 minutes following `README.md`.

---

## 14. Risks & Mitigations

| # | Risk | Impact | Mitigation |
|---|------|--------|------------|
| R1 | **LLM JSON parse failures** — LLM returns malformed JSON violating schema | Pipeline stage fails; potential data loss | Use `instructor` with `max_retries=3`; store `parsed_output=null` on failure; pipeline_run set to `"failed"` without affecting the displayed condition |
| R2 | **Background task data loss on server restart** | Alternate-condition artifact never written | `pipeline_runs` rows with `status="running"` act as sentinel; `scripts/recover_stuck_runs.py` marks stale runs as `"failed"` on startup check |
| R3 | **SQLite write contention** | `OperationalError: database is locked` under concurrent writes | Enable WAL mode (`PRAGMA journal_mode=WAL`); use `aiosqlite`; if persists, serialize writes via `asyncio.Queue` |
| R4 | **Evaluation API cost overruns** | Unexpected spend on judge calls | Default judge is `gpt-4o-mini`; `--dry-run` flag shows estimated cost; `Semaphore(10)` prevents bursts; cost shown in `EvalBatchDetailResponse` |
| R5 | **Prompt drift — editing YAML in place** | Historical telemetry no longer reproducible | Immutability rule enforced in contributing guide; `v{N+1}.yaml` for any change; Git history is the audit trail |
| R6 | **Judge verbosity confound** — longer outputs rated higher | Evaluation bias inflating one condition | Judge rubric explicitly penalizes verbosity; rubric wording reviewed before first eval run |
| R7 | **Schema drift between pipeline stages** | Reviser receives malformed verifier/critic output | Verifier and critic use permissive flat schemas (`list[str]`); Reviser prompt instructs it to handle missing/malformed sections gracefully |
| R8 | **Small sample bias** | Statistical conclusions from <30 turns invalid | README includes recommended minimum dataset size (≥50 turns per condition); `GET /eval/summary` displays N alongside means |

---

## 15. Definition of Done

- [ ] All 9 SQLite tables created and schema matches this PRD exactly.
- [ ] `POST /sessions/{id}/turns` returns valid `FeedbackOutput`-shaped JSON (validated by Pydantic).
- [ ] Both `pipeline_runs` rows exist in DB after every turn (baseline + corrected).
- [ ] All corrected pipeline artifacts (draft, verifier, critic, reviser) stored in `pipeline_artifacts`.
- [ ] `GET /turns/{id}/artifacts` returns 5 artifacts (1 baseline + 4 corrected).
- [ ] Mock LLM mode works with `OPENAI_API_KEY=mock` (no API calls made).
- [ ] `POST /eval/batches` produces `eval_scores` rows for all (item × judge × dimension) combinations.
- [ ] `condition` field never appears in judge prompt input (`eval_scores.condition_revealed == 0`).
- [ ] `GET /eval/batches/{id}/export?format=csv` returns downloadable CSV with all required columns.
- [ ] `GET /health` returns `200 {"status": "ok", ...}`.
- [ ] `pytest tests/ -v` exits 0 with ≥80% line coverage.
- [ ] Streamlit UI runs and displays structured feedback for a Spanish message.
- [ ] `README.md` allows a new user to run the system from scratch in ≤10 minutes.
- [ ] All prompt YAML files are present under `reflexa/prompts/` with correct `version_id` fields.
- [ ] `llm_calls` row written for every LLM call (including mock and eval judge calls).
- [ ] No hardcoded API keys anywhere in the codebase.

---

*End of PRD*
