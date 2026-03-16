# Research Workflow

This document describes the final research workflow around Reflexa's evaluation, export, analysis, reporting, and survey follow-up.

## Script Categories

### Core scripts

These are reusable and part of the main workflow:

| Script | Purpose |
|---|---|
| `scripts/init_db.py` | Initialize or reset the local database |
| `scripts/simulate_sessions.py` | Generate evaluation turns through the API |
| `scripts/run_eval.py` | Create and run offline evaluation batches |
| `scripts/export_results.py` | Export one batch as CSV or JSONL |
| `scripts/export_all.py` | Export database tables for inspection |
| `scripts/analyze_results.py` | Inter-rater reliability and judge-bias analysis |

### Research-only scripts

These are useful for project analysis and report production, but are not required to run the application itself:

| Script | Purpose |
|---|---|
| `scripts/show_stats.py` | Paired tests, per-dimension deltas, judge-level summaries |
| `scripts/generate_report.py` | Comprehensive experiment report PDF |
| `scripts/generate_methodology_pdf.py` | Detailed scoring/methodology PDF |
| `scripts/generate_comparison_pdf.py` | Changed-turn baseline vs corrected comparison PDF |
| `scripts/generate_spanish_pdf.py` | Spanish-only comparison PDF |
| `scripts/generate_comparison.py` | Comparison CSV generation |

These reporting scripts currently expect exported evaluation files to exist locally and are intended for researcher use, not end-user operation.

## Recommended End-to-End Workflow

### 1. Initialize the database

```bash
python3 scripts/init_db.py
```

### 2. Collect turns

Use either the UI/API manually or generate turns through the simulation script:

```bash
python3 scripts/simulate_sessions.py
```

### 3. Run evaluation

```bash
python3 scripts/run_eval.py --notes "Final run"
```

Optional:

```bash
python3 scripts/run_eval.py --dry-run
```

### 4. Export the batch

First inspect available batches:

```bash
python3 scripts/export_results.py --list-batches
```

Then export to a private, ignored output directory:

```bash
python3 scripts/export_results.py --batch-id <id> --format csv   > analysis_and_results/results.csv
python3 scripts/export_results.py --batch-id <id> --format jsonl > analysis_and_results/results.jsonl
```

Avoid exporting to the repository root.

### 5. Analyze results

Inter-rater reliability and judge bias:

```bash
python3 scripts/analyze_results.py analysis_and_results/results.jsonl
```

Paired deltas and score distributions:

```bash
python3 scripts/show_stats.py analysis_and_results/results.jsonl
```

### 6. Generate reports

If you need research PDFs or comparison reports:

```bash
python3 scripts/generate_methodology_pdf.py
python3 scripts/generate_comparison_pdf.py
python3 scripts/generate_report.py
```

These scripts should write outputs into `analysis_and_results/` or another ignored directory.

## Survey Workflow

The final project also included a small survey-based validation step.

Recommended handling for survey artifacts:

- keep raw exports out of git
- do not commit files containing respondent IP addresses or location data
- store survey CSV/XLSX exports only in ignored directories such as `analysis_and_results/`
- generate writeups or summaries into ignored output folders unless you intentionally need a sanitized tracked document

## Privacy Rules

Never commit:

- raw survey exports containing respondent metadata
- root-level evaluation exports such as `results.csv` or `results.jsonl`
- generated PDF reports
- local secrets or keys

Examples of files that should remain private:

- `analysis_and_results/*.csv`
- `analysis_and_results/*.jsonl`
- `analysis_and_results/*.xlsx`
- `analysis_and_results/*.pdf`
- `.sshkey`
- `.sshkey.pub`

## Dependency Notes

The research-only PDF/report scripts depend on `fpdf2`, which is installed through:

```bash
pip install -e ".[dev]"
```

## Final Guidance

Use the repository source files for code and documentation, and treat all generated analyses, exports, and survey data as private working artifacts unless they have been explicitly sanitized for publication.
