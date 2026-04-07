# Reflexa

Reflexa is a research platform for AI-assisted language-learning feedback. For each learner message, it runs a visible `baseline` feedback pipeline and a hidden `corrected` review pipeline, stores both outputs plus intermediate artifacts, and evaluates them offline with blinded LLM judges.

The current system also includes:

- session openers generated at chat start
- conversational replies returned with every feedback package
- a Streamlit frontend for interactive testing
- an offline evaluation/export toolchain
- research-only analysis and PDF/report generation scripts

## Current Status

The end-to-end platform is implemented and usable for:

- collecting learner turns in multiple languages
- running the baseline-first dual-condition pipeline
- storing runs, artifacts, and feedback outputs in SQLite
- running offline blinded evaluation across a configurable judge pool
- exporting results to CSV/JSONL
- generating research analyses and private reports from exported data

The codebase also contains post-evaluation survey/report tooling used during the final project phase. Those scripts are documented, but their generated outputs are intentionally kept out of git.

## Core Design

Every user turn runs both conditions in sequence:

1. `baseline`: a single LLM call that generates the user-visible feedback package
2. `corrected`: the baseline output is reviewed by `verifier` and `critic`, then revised by `reviser`

Important behavior:

- baseline always runs first
- corrected never drafts independently; it only refines the baseline output
- if `DISPLAY_CONDITION=baseline`, corrected runs in the background
- if `DISPLAY_CONDITION=corrected`, baseline still runs first but corrected is awaited and returned

This makes the comparison interpretable: the corrected condition is measured as a direct revision of baseline rather than a separate generation strategy.

## What The User Sees

In the UI, each session starts with an LLM-generated opener in the target language. Each turn then returns:

- a conversational reply
- a corrected utterance
- a structured error list
- explanations
- prioritization and focus guidance
- a practice prompt

Only one condition is shown to the learner. The other condition is stored silently for offline analysis.

## Supported Languages

The current Streamlit UI exposes:

- Spanish
- French
- Portuguese
- Italian
- German
- Japanese

## Quick Start

### 1. Install dependencies

```bash
pip install -e ".[dev]"
```

This installs the app plus development and research-script dependencies.

### 2. Configure the environment

```bash
cp .env.example .env
```

Local development defaults to:

```bash
OPENAI_API_KEY=mock
```

This activates the built-in mock LLM client and avoids real API calls.

### 3. Initialize the database

```bash
python3 scripts/init_db.py
# or
make db
```

### 4. Start the API

```bash
make dev
```

The API will be available at `http://localhost:8000` and Swagger docs at `http://localhost:8000/docs`.

### 5. Start the Streamlit UI

In a second terminal:

```bash
make ui
```

## Tests

Run the full test suite with:

```bash
make test
```

Coverage:

```bash
make cov
```

The repository should be treated as the source of truth for the current test count. Avoid hardcoding a specific passing-test total in downstream documentation because it changes as the project evolves.

## Environment Variables

### Core runtime

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | `mock` | Main pipeline LLM provider key; `mock` activates the deterministic mock client |
| `DATABASE_URL` | `sqlite+aiosqlite:///reflexa.db` | SQLite database location |
| `LOG_LEVEL` | `INFO` | Backend logging verbosity |
| `MEMORY_TURNS` | `10` | Number of visible prior turns included in prompt memory |
| `MAX_MESSAGE_LENGTH` | `2000` | Maximum accepted input length for a learner message |
| `DISPLAY_CONDITION` | `baseline` | Which condition is returned to the UI |
| `LLM_TIMEOUT` | `30` | Timeout for a single LLM call in seconds |

### Model configuration

| Variable | Default | Purpose |
|---|---|---|
| `LLM_MODEL` | `gpt-4o-mini` | Main generation model for baseline and reviser |
| `REVIEW_MODEL` | `gpt-4o-mini` | Review model for verifier and critic |
| `OPENROUTER_API_KEY` | empty | Key used for evaluation judge calls |
| `JUDGE_MODELS` | `x-ai/grok-4-fast,anthropic/claude-3.5-haiku,google/gemini-2.0-flash-001` | Comma-separated judge model pool |

### API and UI

| Variable | Default | Purpose |
|---|---|---|
| `API_HOST` | `127.0.0.1` | FastAPI bind host |
| `API_PORT` | `8000` | FastAPI port |
| `BACKEND_URL` | `http://localhost:8000` | Backend URL used by Streamlit |

### Prompt version overrides

If unset, Reflexa uses the latest prompt file under each prompt directory.

| Variable | Latest currently checked in |
|---|---|
| `BASELINE_PROMPT_VERSION` | `baseline/v4` |
| `PIPELINE_DRAFT_PROMPT_VERSION` | `pipeline_draft/v1` |
| `PIPELINE_VERIFIER_PROMPT_VERSION` | `pipeline_verifier/v4` |
| `PIPELINE_CRITIC_PROMPT_VERSION` | `pipeline_critic/v4` |
| `PIPELINE_REVISER_PROMPT_VERSION` | `pipeline_reviser/v6` |
| `EVAL_JUDGE_PROMPT_VERSION` | `eval_judge/v2` |
| `SESSION_OPENER_PROMPT_VERSION` | `session_opener/v2` |

## API Summary

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check for DB and LLM mode |
| `POST` | `/sessions` | Create a new session and return `opener_message` |
| `GET` | `/sessions/{id}` | Session metadata and turn count |
| `GET` | `/sessions/{id}/history` | Recent turn history |
| `POST` | `/sessions/{id}/turns` | Submit a learner message and get the visible feedback package |
| `GET` | `/turns/{id}/artifacts` | Inspect saved pipeline artifacts for a turn |
| `GET` | `/turns/{id}/feedback/{condition}` | Retrieve stored feedback for one condition |
| `POST` | `/eval/batches` | Queue evaluation for unscored or selected outputs |
| `GET` | `/eval/batches/{id}` | Batch metadata and status |
| `GET` | `/eval/batches/{id}/results` | Blinded score records |
| `GET` | `/eval/batches/{id}/export?format=csv|jsonl` | Stream results for one batch |
| `GET` | `/eval/summary` | Aggregate condition-by-dimension summary |

## Evaluation Model

The offline judge scores each feedback output on six dimensions:

1. `linguistic_correctness`
2. `explanation_quality`
3. `actionability`
4. `level_appropriateness`
5. `prioritization_and_focus`
6. `conversational_quality`

Judges are blinded to condition. The condition label is never included in the judge prompt.

## Research Workflow

The most common workflow is:

1. collect or simulate turns
2. run evaluation
3. export a batch
4. analyze the exported files
5. generate private reports

Typical commands:

```bash
# Generate or collect turns
python3 scripts/simulate_sessions.py

# Run evaluation
python3 scripts/run_eval.py --notes "Final run"

# Inspect/export batches
python3 scripts/export_results.py --list-batches
python3 scripts/export_results.py --batch-id <id> --format csv   > analysis_and_results/results.csv
python3 scripts/export_results.py --batch-id <id> --format jsonl > analysis_and_results/results.jsonl

# Analyze exported results
python3 scripts/analyze_results.py analysis_and_results/results.jsonl
python3 scripts/show_stats.py analysis_and_results/results.jsonl
```

See `docs/research_workflow.md` for a fuller description of core scripts, research-only scripts, and where outputs should live.

## Research Scripts

The repository contains two broad categories of scripts:

- reusable operational scripts such as `init_db.py`, `run_eval.py`, `export_results.py`, `export_all.py`, `simulate_sessions.py`, and `analyze_results.py`
- research-only analysis/report generators such as `generate_report.py`, `generate_methodology_pdf.py`, `generate_comparison_pdf.py`, `generate_spanish_pdf.py`, `generate_comparison.py`, and `show_stats.py`

The report generators are useful for reproducing the final project materials, but they are not required to run the app itself.

## Deployment

The repository includes Docker and nginx configuration for a simple three-service deployment:

- `api`
- `ui`
- `nginx`

Bring it up with:

```bash
docker compose up -d --build
```

Then initialize the database once:

```bash
docker compose exec api python3 scripts/init_db.py
```

The UI is served through nginx on port `80`.

## Repository Hygiene

The following should be treated as private or generated and should not be committed:

- `analysis_and_results/`
- exported `results*.csv` / `results*.jsonl`
- `export/`
- survey exports containing IP/location metadata
- local tool state such as `.claude/`, `.Rhistory`
- any keys such as `.sshkey` or `.sshkey.pub`

If you generate experiment reports locally, write them into `analysis_and_results/` rather than the repo root.

## Additional Documentation

- `docs/research_workflow.md` — evaluation, export, analysis, reporting, and privacy workflow
