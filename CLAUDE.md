# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (includes dev deps)
pip install -e ".[dev]"

# Initialise / reset the local SQLite database
python3 scripts/init_db.py

# Run all tests
pytest tests/ -v

# Run a single test
pytest tests/test_db_schema.py::test_all_tables_exist -v

# Run with coverage
pytest tests/ --cov=reflexa --cov-report=term-missing
```

The system runs with `OPENAI_API_KEY=mock` for local development (no real API calls). Copy `.env.example` → `.env` to configure.

## Architecture

Reflexa is a **research platform** that runs two LLM feedback pipelines for every user message, stores all outputs, and evaluates them offline with an LLM judge.

### Two-condition design (core concept)
Every user turn runs both conditions sequentially:
- **Baseline** — single LLM call → `FeedbackOutput` (always runs first; shown to user)
- **Corrected** — takes the Baseline output as its draft → (Verifier ‖ Critic) → Reviser → `FeedbackOutput` (runs in background)

The Corrected pipeline never generates an independent draft. It refines the Baseline output through three stages: Verifier and Critic review it in parallel, then Reviser integrates their reports. This ensures the evaluation measures the direct improvement attributable to the correction pipeline. Both outputs are stored for offline comparison. The active display condition is set by `DISPLAY_CONDITION` in config.

### Data flow
```
HTTP POST /sessions/{id}/turns
  └─ orchestrator.run_both_conditions()
       ├─ await run_baseline()              → returned in HTTP response
       └─ asyncio.create_task(             → completes after response sent
            run_corrected(baseline_output))
            ↓ (both write to SQLite)
  pipeline_runs → pipeline_artifacts → feedback_outputs
                                            ↓
                                       eval_items (in eval batch)
                                            ↓
                                       eval_scores (LLM judge, blinded)
```

### Key modules

| Module | Role |
|--------|------|
| `reflexa/config.py` | Single `Settings` singleton via pydantic-settings; `settings.is_mock` drives LLM selection |
| `reflexa/db/models.py` | 9 SQLAlchemy ORM tables (all PKs are UUID v4 TEXT, timestamps ISO 8601 UTC TEXT) |
| `reflexa/db/engine.py` | `build_engine()` attaches SQLite pragmas (`FK=ON`, `WAL`); `get_db()` is the FastAPI dependency |
| `reflexa/db/crud.py` | All DB reads/writes — fully implemented |
| `reflexa/schemas/feedback.py` | `FeedbackOutput` + `ErrorItem` — core Pydantic output schema; includes `conversation_reply` field |
| `reflexa/schemas/api.py` | FastAPI request/response schemas; `SessionResponse` includes `opener_message`, `FeedbackResponse` includes `conversation_reply` |
| `reflexa/schemas/opener.py` | `SessionOpenerOutput` — schema for session opener LLM call |
| `reflexa/llm/cost.py` | `estimate_cost(model_id, tokens_in, tokens_out) -> float \| None` — USD cost table (per 1M tokens) |
| `reflexa/llm/client.py` | `LLMClient` wraps `instructor` + `AsyncOpenAI`; writes `llm_calls` row on every call (success or failure). `build_llm_client(settings)` factory selects real vs mock. |
| `reflexa/llm/mock.py` | `MockLLMClient` — returns deterministic responses; register new types via `_register(ModelClass, data_dict)`. Activated when `OPENAI_API_KEY=mock`. |
| `reflexa/prompts/` | Versioned YAML prompt files — **immutable once committed**; new version = new `v{N+1}.yaml`. Current latest: `baseline/v3`, `pipeline_reviser/v3`, `session_opener/v1`, others `v1`. `pipeline_draft/v1` exists but is no longer called at runtime. |
| `reflexa/prompt_loader.py` | `PromptLoader` class + module singleton `loader`. `get_prompt(name)` respects env-var overrides then falls back to `latest()`. `PromptTemplate.to_messages(**kwargs)` renders both parts into an OpenAI messages list. |
| `reflexa/pipeline/baseline.py` | `run_baseline()` — single-call feedback pipeline |
| `reflexa/pipeline/corrected.py` | `run_corrected(ctx, baseline_feedback)` — 3 active stages: (Verifier ‖ Critic) → Reviser, using baseline output as draft (no independent draft LLM call) |
| `reflexa/pipeline/orchestrator.py` | `run_both_conditions()` — always awaits baseline first, then fires corrected as background task passing baseline output as draft |
| `reflexa/pipeline/opener.py` | `run_session_opener()` — generates opening message in target language at session start |
| `reflexa/api/` | FastAPI app + routers for sessions, chat, artifacts, eval |
| `reflexa/eval/` | Offline harness: blinded judge scoring → `eval_scores`; export to CSV/JSONL |
| `reflexa/memory.py` | `ConversationMemory` — builds history list including `conversation_reply` turns |
| `ui/app.py` | Streamlit frontend; opener bubble on session start; reply-first layout with feedback in expander |

### Database rules
- All PKs: UUID v4 `TEXT`
- All timestamps: ISO 8601 UTC `TEXT`
- JSON blobs (`error_list`, `judge_models`, etc.): stored as `TEXT`, serialised with `json.dumps`
- `Session.metadata_` maps to column `"metadata"` (Python keyword conflict)
- `PRAGMA foreign_keys = ON` and `PRAGMA journal_mode = WAL` are set at engine connect time via a `sync_engine` event listener in `engine.py`, **not** in the fixture — the test `db_session` fixture uses a bare in-memory engine without these pragmas

### Prompt versioning contract
Prompt YAMLs live at `reflexa/prompts/{name}/v{N}.yaml`. **Never edit a file after it is committed** — always create `v{N+1}.yaml`. The `prompt_version_id` field is stored on every `llm_calls` and `pipeline_artifacts` row for full reproducibility.

### Evaluation blinding
`feedback_output.condition` must **never** appear in the judge prompt. Post-analysis reveals condition by joining `eval_scores → eval_items → feedback_outputs`. The random seed used for `display_order` shuffling is stored in `eval_batches.notes`.

### Eval harness (Phase 4)
- `reflexa/eval/judge.py` — `score_item()` scores one (item, model, dimension) triple; never passes `condition` to the judge prompt
- `reflexa/eval/harness.py` — `run_evaluation(batch_id, llm_client)` runs all (item × model × dimension) concurrently with `asyncio.Semaphore(10)`; uses its own DB session
- `reflexa/eval/export.py` — `stream_csv()` / `stream_jsonl()` async generators for `StreamingResponse`
- `scripts/run_eval.py` — CLI with `--dry-run`, `--judge-models`, `--notes`
- `scripts/export_results.py` — CLI with `--batch-id`, `--format`, `--list-batches`

### Conversational flow (implemented after Phase 4)
- `Session.opener_message` — LLM generates an opening message at session creation time; stored in DB and returned in `POST /sessions` response
- `FeedbackOutput.conversation_reply` — every pipeline turn returns a conversational follow-up in the target language; stored in `feedback_outputs` and surfaced in the API
- UI: opener shown as first assistant bubble; per-turn layout is reply-first with structured feedback collapsed in an expander
- Prompts `baseline/v3` and `pipeline_reviser/v3` are the current latest versions (richer conversation_reply, temperature 0.5, max_tokens 1500); `session_opener/v1` is new
- Curly braces in YAML schema examples must be double-escaped (`{{` / `}}`) because `PromptTemplate.to_messages()` uses `str.format_map()`

### Implementation phases
The PRD (`prd.md`) defines 5 phases (0–4) plus the conversational flow extension. All are complete. Phase 5 (hardening: timeouts, structured logging, `/health`, README, Makefile, graceful failure, ≥80% coverage) remains.

### Important: asyncio.gather + SQLAlchemy sessions
`asyncio.gather` runs coroutines concurrently on the same event loop. Calling `await db.flush()` inside two coroutines that share a session **will race** and raise `Session is already flushing`. The fix used in `create_llm_call` is to omit the explicit flush — SQLAlchemy's `autoflush=True` (the default) triggers a flush automatically before any subsequent `select()`, and UUIDs are pre-generated so no flush is needed for the returned object. Any CRUD function called inside `asyncio.gather` must follow this pattern.
