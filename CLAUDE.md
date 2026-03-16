# CLAUDE.md

Repository guidance for coding agents working in Reflexa.

## Commands

```bash
# Install app + dev/reporting dependencies
pip install -e ".[dev]"

# Initialize or reset the local SQLite database
python3 scripts/init_db.py

# Run all tests
pytest tests/ -v

# Run coverage
pytest tests/ --cov=reflexa --cov-report=term-missing

# Start backend + UI
make dev
make ui
```

Local development defaults to `OPENAI_API_KEY=mock`, so no real API key is required unless you intentionally switch to live models.

## Architecture

Reflexa is a research platform for AI-generated language-learning feedback with a baseline-first two-condition design.

### Two-condition flow

Every learner turn runs both conditions sequentially:

- `baseline`: one LLM call produces the visible feedback package
- `corrected`: the baseline output is reviewed by verifier and critic, then revised

Important implementation facts:

- baseline always runs first
- corrected never drafts independently
- if `DISPLAY_CONDITION=baseline`, corrected runs in the background
- if `DISPLAY_CONDITION=corrected`, corrected is awaited after baseline

### User-visible experience

- `POST /sessions` creates a session and returns an `opener_message`
- each turn returns a `conversation_reply` plus structured feedback
- the Streamlit UI shows the reply first and keeps detailed feedback inside an expander

### Data flow

```text
POST /sessions/{id}/turns
  -> baseline pipeline
  -> corrected pipeline (background or awaited, depending on DISPLAY_CONDITION)
  -> pipeline_runs / pipeline_artifacts / feedback_outputs
  -> eval_items / eval_scores during offline evaluation
```

## Key Modules

| Module | Role |
|---|---|
| `reflexa/config.py` | Settings singleton and environment configuration |
| `reflexa/db/models.py` | SQLAlchemy models for sessions, turns, outputs, artifacts, LLM calls, and evaluation |
| `reflexa/db/crud.py` | DB read/write helpers |
| `reflexa/llm/client.py` | Structured LLM client with telemetry and retries |
| `reflexa/llm/mock.py` | Deterministic mock client for local development |
| `reflexa/pipeline/baseline.py` | Visible feedback generation |
| `reflexa/pipeline/corrected.py` | Verifier + critic + reviser correction flow |
| `reflexa/pipeline/opener.py` | Session opener generation |
| `reflexa/pipeline/orchestrator.py` | Baseline-first orchestration |
| `reflexa/eval/judge.py` | Blinded scoring across six evaluation dimensions |
| `ui/app.py` | Streamlit frontend |

## Prompt Versioning

Prompt YAMLs live under `reflexa/prompts/{name}/v{N}.yaml` and are immutable once committed.

Current latest prompt versions checked into the repo:

- `baseline/v4`
- `pipeline_draft/v1`
- `pipeline_verifier/v4`
- `pipeline_critic/v4`
- `pipeline_reviser/v6`
- `eval_judge/v2`
- `session_opener/v2`

If you need to change prompt behavior, add a new version file rather than editing an old one in place.

## Evaluation

The judge scores six dimensions:

- `linguistic_correctness`
- `explanation_quality`
- `actionability`
- `level_appropriateness`
- `prioritization_and_focus`
- `conversational_quality`

Condition must remain blinded in the judge prompt.

## Hardening / Project Status

The codebase already includes the major hardening items that were once planned as a later phase:

- `/health` endpoint
- request logging middleware
- graceful validation and pipeline-error handling
- deployment configuration via Docker/nginx
- dedicated hardening tests in `tests/test_hardening.py`

Treat the system as implemented and documented, with ongoing work focused on research outputs rather than unfinished platform basics.

## Research Tooling

Operational scripts:

- `scripts/init_db.py`
- `scripts/run_eval.py`
- `scripts/export_results.py`
- `scripts/export_all.py`
- `scripts/simulate_sessions.py`
- `scripts/analyze_results.py`

Research-only report/analysis scripts:

- `scripts/show_stats.py`
- `scripts/generate_report.py`
- `scripts/generate_methodology_pdf.py`
- `scripts/generate_comparison_pdf.py`
- `scripts/generate_spanish_pdf.py`

Generated artifacts belong in ignored locations such as `analysis_and_results/`, not in tracked repo files.

## Safety / Repo Hygiene

Do not commit:

- `analysis_and_results/`
- `export/`
- root-level `results*.csv` or `results*.jsonl`
- survey exports with respondent metadata
- `.sshkey`, `.sshkey.pub`, or other keys
- local tool state such as `.claude/` and `.Rhistory`

If documentation and code disagree, prefer the live code and update the docs to match.
