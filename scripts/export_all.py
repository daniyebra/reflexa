"""
CLI — export all Reflexa database tables to CSV or JSONL.

Usage:
    python scripts/export_all.py                         # CSV to ./export/
    python scripts/export_all.py --format jsonl          # JSONL to ./export/
    python scripts/export_all.py --output-dir /tmp/dump  # custom directory
    python scripts/export_all.py --table sessions        # single table only
    python scripts/export_all.py --list-tables           # show available tables
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import io
import json
import sys
from pathlib import Path

# Ensure the repo root is on sys.path when run directly.
sys.path.insert(0, str(Path(__file__).parent.parent))

# Ordered list of (table_name, ORM model name) pairs.
# Order respects foreign-key dependencies (parents before children).
_TABLES = [
    "sessions",
    "turns",
    "pipeline_runs",
    "feedback_outputs",
    "pipeline_artifacts",
    "llm_calls",
    "eval_batches",
    "eval_items",
    "eval_scores",
]


def _get_model(table_name: str):
    from reflexa.db import models

    mapping = {
        "sessions": models.Session,
        "turns": models.Turn,
        "pipeline_runs": models.PipelineRun,
        "feedback_outputs": models.FeedbackOutput,
        "pipeline_artifacts": models.PipelineArtifact,
        "llm_calls": models.LLMCall,
        "eval_batches": models.EvalBatch,
        "eval_items": models.EvalItem,
        "eval_scores": models.EvalScore,
    }
    return mapping[table_name]


def _row_to_dict(row, columns: list[str]) -> dict:
    return {col: getattr(row, col, None) for col in columns}


def _columns_for(model) -> list[str]:
    return [col.key for col in model.__table__.columns]


async def _export_table(
    table_name: str,
    fmt: str,
    output_dir: Path | None,
) -> None:
    from sqlalchemy import select
    from reflexa.db.engine import AsyncSessionLocal

    model = _get_model(table_name)
    columns = _columns_for(model)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(model))
        rows = result.scalars().all()

    if output_dir is not None:
        ext = "csv" if fmt == "csv" else "jsonl"
        out_path = output_dir / f"{table_name}.{ext}"
        out = out_path.open("w", encoding="utf-8", newline="")
    else:
        out = None  # write to stdout

    def write(text: str) -> None:
        if out:
            out.write(text)
        else:
            sys.stdout.write(text)

    try:
        if fmt == "csv":
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            write(buf.getvalue())
            for row in rows:
                buf = io.StringIO()
                writer = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n")
                writer.writerow(_row_to_dict(row, columns))
                write(buf.getvalue())
        else:
            for row in rows:
                write(json.dumps(_row_to_dict(row, columns), ensure_ascii=False, default=str) + "\n")
    finally:
        if out:
            out.close()

    if output_dir is not None:
        print(f"  {table_name:<22} → {out_path}  ({len(rows)} rows)")


async def _run_export(tables: list[str], fmt: str, output_dir: Path | None) -> None:
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"Exporting {len(tables)} table(s) to {output_dir}/\n")

    for table_name in tables:
        await _export_table(table_name, fmt, output_dir)

    if output_dir is not None:
        print(f"\nDone. {len(tables)} file(s) written to {output_dir}/")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export all Reflexa database tables to CSV or JSONL.",
    )
    parser.add_argument(
        "--format",
        choices=["csv", "jsonl"],
        default="csv",
        help="Output format (default: csv)",
    )
    parser.add_argument(
        "--output-dir",
        default="export",
        metavar="DIR",
        help="Directory to write files into (default: ./export). Use '-' to write to stdout.",
    )
    parser.add_argument(
        "--table",
        choices=_TABLES,
        default=None,
        metavar="TABLE",
        help="Export a single table only (default: all tables)",
    )
    parser.add_argument(
        "--list-tables",
        action="store_true",
        help="List available tables and exit",
    )
    args = parser.parse_args()

    if args.list_tables:
        print("Available tables:")
        for t in _TABLES:
            print(f"  {t}")
        return

    tables = [args.table] if args.table else _TABLES
    output_dir = None if args.output_dir == "-" else Path(args.output_dir)

    asyncio.run(_run_export(tables, args.format, output_dir))


if __name__ == "__main__":
    main()
