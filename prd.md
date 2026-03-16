# Reflexa: Final Project Specification

> Version: 2.0  
> Date: 2026-03-14  
> Status: Implemented

## Purpose

This document describes the system that is actually implemented in the repository. It replaces the original planning-era PRD as the source of truth for the final project state.

Reflexa is a research platform for AI-generated language-learning feedback. It compares a visible baseline feedback pipeline against a hidden corrected pipeline, stores both outputs, evaluates them offline with blinded judges, and supports follow-on analysis and survey-based validation work.

## Final Scope

### Primary goals achieved

- collect structured learner-feedback outputs for every turn
- run two generation conditions per turn and store both
- expose intermediate pipeline artifacts for inspection
- support offline blinded evaluation with multiple judge models
- export evaluation results to CSV and JSONL
- provide an interactive UI for researcher-led testing
- support post-hoc analysis, report generation, and survey-based validation

### Non-goals

- production-scale multi-user concurrency
- authentication and account management
- long-term learner modeling
- direct measurement of learning outcomes inside the platform
- real-time streaming UX

## End-to-End System

### High-level flow

```text
Streamlit UI / API client
  -> create session
  -> opener message generated
  -> submit learner turn
  -> baseline feedback generated and returned
  -> corrected feedback generated in background or synchronously
  -> both conditions stored in SQLite
  -> offline evaluation batches score stored outputs
  -> results exported for analysis/reporting
```

### Two-condition design

For every learner turn:

1. `baseline`
   - one LLM call
   - produces the visible feedback package
   - always runs first

2. `corrected`
   - takes the baseline output as its draft
   - runs `verifier` and `critic` in parallel
   - sends their findings to `reviser`
   - stores a revised feedback package

Important property:

- corrected does **not** produce an independent first draft
- the experiment therefore measures revision quality, not two unrelated generators

### Display behavior

- if `DISPLAY_CONDITION=baseline`, baseline is returned immediately and corrected runs in the background
- if `DISPLAY_CONDITION=corrected`, baseline still runs first, then corrected is awaited and returned

## User Experience

### Session start

`POST /sessions` creates a session and returns:

- `id`
- `target_language`
- `proficiency_level`
- `created_at`
- `opener_message`

The opener is generated in the target language and displayed as the first assistant message in the Streamlit UI.

### Turn response

Each turn returns a feedback package containing:

- `conversation_reply`
- `corrected_utterance`
- `error_list`
- `explanations`
- `prioritization_and_focus`
- `practice_prompt`
- `pipeline_run_id`
- `latency_ms`

The UI displays the conversational reply first, then the detailed feedback in an expandable section.

### Languages

The current UI exposes:

- Spanish
- French
- Portuguese
- Italian
- German
- Japanese

### Levels

The UI supports:

- `A1`
- `A2`
- `B1`
- `B2`
- `C1`
- `C2`

## Implemented Architecture

### Major components

| Component | Purpose |
|---|---|
| `ui/app.py` | Streamlit interface for sessions, chat, and feedback display |
| `reflexa/api/main.py` | FastAPI app, middleware, `/health`, exception handling |
| `reflexa/api/routers/` | Session, turn, artifact, and evaluation endpoints |
| `reflexa/pipeline/` | Baseline, corrected, opener, and orchestration logic |
| `reflexa/llm/` | Real and mock LLM clients plus cost estimation |
| `reflexa/db/` | Engine, ORM models, CRUD helpers |
| `reflexa/eval/` | Blinded judge flow, harness, and export support |
| `scripts/` | DB setup, simulation, evaluation, export, analysis, and reporting |

### Deployment

The repository now includes deployment support:

- `Dockerfile`
- `docker-compose.yml`
- `nginx.conf`
- `Procfile`

This means the old planning assumption that containerization was out of scope is no longer true for the final project state.

## Data Model

All primary keys are UUID v4 strings. All timestamps are ISO 8601 UTC strings.

### Core tables

1. `sessions`
   - session metadata
   - includes `opener_message`

2. `turns`
   - one learner message per turn
   - stores `display_condition`

3. `pipeline_runs`
   - one row per turn/condition
   - tracks status and failure state

4. `feedback_outputs`
   - final structured feedback for each condition
   - includes `conversation_reply`

5. `pipeline_artifacts`
   - saved intermediate stage inputs/outputs

6. `llm_calls`
   - telemetry for every LLM request

7. `eval_batches`
   - one offline evaluation run

8. `eval_items`
   - randomized scoring items for a batch

9. `eval_scores`
   - one score per item, judge, and dimension

### Database conventions

- JSON payloads are stored as serialized text
- SQLite foreign keys are enabled on connect
- WAL mode is enabled on connect
- `Session.metadata_` maps to SQL column `metadata`

## API

### Sessions

- `POST /sessions`
- `GET /sessions/{session_id}`
- `GET /sessions/{session_id}/history`

### Chat

- `POST /sessions/{session_id}/turns`

### Artifacts / stored outputs

- `GET /turns/{turn_id}/artifacts`
- `GET /turns/{turn_id}/feedback/{condition}`

### Evaluation

- `POST /eval/batches`
- `GET /eval/batches/{batch_id}`
- `GET /eval/batches/{batch_id}/results`
- `GET /eval/batches/{batch_id}/export?format=csv|jsonl`
- `GET /eval/summary`

### Evaluation API behavior

Important implementation detail:

- the server uses configured `JUDGE_MODELS`
- client-supplied `judge_model_ids` are ignored
- this prevents the API caller from silently changing the judge pool

## Prompting

Prompt YAMLs live under:

- `reflexa/prompts/baseline/`
- `reflexa/prompts/pipeline_draft/`
- `reflexa/prompts/pipeline_verifier/`
- `reflexa/prompts/pipeline_critic/`
- `reflexa/prompts/pipeline_reviser/`
- `reflexa/prompts/eval_judge/`
- `reflexa/prompts/session_opener/`

Prompt files are immutable after commit. To change prompt behavior, create a new `v{N+1}.yaml`.

### Latest checked-in prompt versions

- `baseline/v4`
- `pipeline_draft/v1`
- `pipeline_verifier/v4`
- `pipeline_critic/v4`
- `pipeline_reviser/v6`
- `eval_judge/v2`
- `session_opener/v2`

## Evaluation Harness

### Blinding

The judge prompt must never receive the true `condition`.

Condition is recovered only during later analysis by joining:

- `eval_scores`
- `eval_items`
- `feedback_outputs`

### Judge pool

The final system supports a configurable multi-model judge pool using:

- `OPENROUTER_API_KEY`
- `JUDGE_MODELS`

### Dimensions

The implemented evaluation uses six dimensions:

1. `linguistic_correctness`
2. `explanation_quality`
3. `actionability`
4. `level_appropriateness`
5. `prioritization_and_focus`
6. `conversational_quality`

### Output format

Evaluation can be exported as:

- CSV
- JSONL

## Hardening and Observability

The final project includes the previously planned hardening layer:

- `/health` endpoint
- request logging middleware with `X-Request-ID`
- validation error normalization
- graceful pipeline failure responses
- configurable timeouts
- Docker/nginx deployment support
- tests covering hardening behavior

This means the earlier “Phase 5 remains” planning status is no longer accurate.

## Scripts

### Core operational scripts

- `scripts/init_db.py`
- `scripts/simulate_sessions.py`
- `scripts/run_eval.py`
- `scripts/export_results.py`
- `scripts/export_all.py`
- `scripts/analyze_results.py`

### Research-only analysis/report scripts

- `scripts/show_stats.py`
- `scripts/generate_report.py`
- `scripts/generate_methodology_pdf.py`
- `scripts/generate_comparison_pdf.py`
- `scripts/generate_spanish_pdf.py`
- `scripts/generate_comparison.py`

These research-only scripts are not required for app runtime, but they are part of the final analysis workflow used during the project.

## Privacy and Repository Hygiene

The following must not be committed:

- `analysis_and_results/`
- exported `results*.csv` / `results*.jsonl`
- `export/`
- survey exports with respondent IP/location data
- local state such as `.claude/`, `.Rhistory`
- keys such as `.sshkey` and `.sshkey.pub`

Generated reports belong in ignored output directories, not in tracked source folders.

## Final Project Interpretation

Reflexa should be understood as:

- an implemented research platform
- a baseline-vs-corrected feedback comparison system
- a tooling stack for evaluation, export, and analysis
- a project that has already moved beyond the original planning document into a documented final state

For up-to-date operational details, prefer:

- `README.md` for setup and workflow
- `CLAUDE.md` for implementation guidance
- `docs/research_workflow.md` for analysis/reporting practice
