# Reflexa

A research platform that runs two LLM feedback pipelines in parallel for every language-learner message, stores all outputs, and evaluates them offline with an LLM judge.

## Quick Start

### 1. Install dependencies

```bash
pip install -e ".[dev]"
```

### 2. Configure environment

```bash
cp .env.example .env
```

The default `.env` sets `OPENAI_API_KEY=mock`, which activates the built-in mock LLM — no API key required for local development.

To use a real OpenAI key, set:

```
OPENAI_API_KEY=sk-...
```

### 3. Initialise the database

```bash
python3 scripts/init_db.py
# or
make db
```

### 4. Start the API server

```bash
make dev
# or
OPENAI_API_KEY=mock uvicorn reflexa.api.main:app --reload
```

API is available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

### 5. Start the Streamlit UI (optional)

In a second terminal:

```bash
make ui
# or
streamlit run ui/app.py
```

---

## Running Tests

```bash
make test          # all tests, verbose
make cov           # with line coverage report
```

All 135 tests pass with `OPENAI_API_KEY=mock` (no real API calls).

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | `mock` | Set to `mock` for local dev; real key for live LLM |
| `DATABASE_URL` | `sqlite+aiosqlite:///reflexa.db` | SQLite database path |
| `LOG_LEVEL` | `INFO` | Logging verbosity (`DEBUG`/`INFO`/`WARNING`/`ERROR`) |
| `DISPLAY_CONDITION` | `baseline` | Which pipeline is shown to the user (`baseline`/`corrected`) |
| `LLM_MODEL` | `gpt-4o-mini` | OpenAI model for pipeline calls |
| `LLM_TIMEOUT` | `30` | LLM call timeout in seconds |
| `MEMORY_TURNS` | `10` | Number of prior turns included in conversation history |
| `MAX_MESSAGE_LENGTH` | `2000` | Maximum characters in a user message |
| `EVAL_JUDGE_MODEL` | `gpt-4o-mini` | Model used for offline evaluation scoring |
| `API_HOST` | `127.0.0.1` | FastAPI bind address |
| `API_PORT` | `8000` | FastAPI port |
| `BACKEND_URL` | `http://localhost:8000` | URL the Streamlit UI uses to reach the API |

Prompt version overrides (defaults to latest version if unset):

```
BASELINE_PROMPT_VERSION=baseline/v1
PIPELINE_DRAFT_PROMPT_VERSION=pipeline_draft/v1
PIPELINE_VERIFIER_PROMPT_VERSION=pipeline_verifier/v1
PIPELINE_CRITIC_PROMPT_VERSION=pipeline_critic/v1
PIPELINE_REVISER_PROMPT_VERSION=pipeline_reviser/v1
EVAL_JUDGE_PROMPT_VERSION=eval_judge/v1
```

---

## Running Offline Evaluation

### 1. Collect turns

Start a session and submit at least a few messages via the UI or API. Each turn automatically generates two `feedback_output` rows (one per condition).

### 2. Run the evaluator

```bash
make eval
# or with options:
python3 scripts/run_eval.py --judge-models gpt-4o-mini gpt-4o --notes "Run 1"
python3 scripts/run_eval.py --dry-run   # estimate cost without making calls
```

### 3. Export results

```bash
make export                                          # list available batches
python3 scripts/export_results.py --list-batches
python3 scripts/export_results.py --batch-id <id> --format csv   > results.csv
python3 scripts/export_results.py --batch-id <id> --format jsonl > results.jsonl
```

### 4. Check summary via API

```
GET http://localhost:8000/eval/summary
```

Returns mean ± std per condition × dimension.

---

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | DB + LLM connectivity check |
| `POST` | `/sessions` | Create a new session |
| `GET` | `/sessions/{id}` | Session metadata and turn count |
| `GET` | `/sessions/{id}/history` | Last N turns |
| `POST` | `/sessions/{id}/turns` | Submit a message; returns feedback |
| `GET` | `/turns/{id}/artifacts` | All pipeline artifacts for a turn |
| `GET` | `/turns/{id}/feedback/{condition}` | Feedback for a specific condition |
| `POST` | `/eval/batches` | Create and queue an evaluation batch |
| `GET` | `/eval/batches/{id}` | Batch status and progress |
| `GET` | `/eval/batches/{id}/results` | All scores (blinded) |
| `GET` | `/eval/batches/{id}/export?format=csv\|jsonl` | Download results |
| `GET` | `/eval/summary` | Aggregate stats per condition × dimension |

Full interactive docs: `http://localhost:8000/docs`

---

## Architecture

Every user message triggers **both** pipelines simultaneously:

- **Baseline** — single LLM call → `FeedbackOutput`
- **Corrected** — 4-stage pipeline: Draft → (Verifier ‖ Critic) → Reviser → `FeedbackOutput`

One condition is shown to the user; the other runs silently in the background. Both outputs are stored for offline comparison.

The active display condition is set by `DISPLAY_CONDITION` in `.env`.

See `prd.md` for the full product requirements document.

---

## Prompt Versioning

Prompt YAML files live at `reflexa/prompts/{name}/v{N}.yaml` and are **immutable once committed**. To change a prompt, create `v{N+1}.yaml`. The `prompt_version_id` is stored on every `llm_calls` row for full reproducibility.

---

## Recommended Dataset Size

For statistically meaningful evaluation results, collect ≥ 50 turns per condition before running the evaluator. The `GET /eval/summary` endpoint displays N alongside means so you can assess sample size.
