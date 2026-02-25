.PHONY: dev test eval export

## Start the API server in development mode (mock LLM, auto-reload)
dev:
	OPENAI_API_KEY=mock uvicorn reflexa.api.main:app \
		--host 127.0.0.1 --port 8000 --reload

## Run the Streamlit UI (requires the API to be running)
ui:
	streamlit run ui/app.py

## Run all tests with verbose output
test:
	pytest tests/ -v

## Run all tests with coverage report
cov:
	pytest tests/ --cov=reflexa --cov-report=term-missing

## Initialise (or reset) the local SQLite database
db:
	python3 scripts/init_db.py

## Run offline evaluation against all unscored feedback outputs (mock LLM)
eval:
	OPENAI_API_KEY=mock python3 scripts/run_eval.py

## List completed evaluation batches and export the most recent one as CSV
export:
	python3 scripts/export_results.py --list-batches
