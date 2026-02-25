"""
CLI — export evaluation results to CSV or JSONL.

Usage:
    python scripts/export_results.py --batch-id <id> [--format csv|jsonl] [--output results.csv]
    python scripts/export_results.py --list-batches
"""
from __future__ import annotations

import argparse
import asyncio
import sys


async def _list_batches() -> None:
    from reflexa.db.engine import AsyncSessionLocal
    from reflexa.db import crud
    from reflexa.db.models import EvalBatch
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(EvalBatch).order_by(EvalBatch.created_at.desc()))
        batches = result.scalars().all()

    if not batches:
        print("No eval batches found.")
        return

    print(f"{'ID':<38}  {'Status':<12}  {'Created':<28}  Notes")
    print("-" * 100)
    for b in batches:
        print(f"{b.id:<38}  {b.status:<12}  {b.created_at:<28}  {b.notes or ''}")


async def _export(batch_id: str, fmt: str, output_path: str | None) -> None:
    from reflexa.db.engine import AsyncSessionLocal
    from reflexa.db import crud

    async with AsyncSessionLocal() as db:
        batch = await crud.get_eval_batch(db, batch_id)
        if not batch:
            print(f"Error: eval batch {batch_id!r} not found.", file=sys.stderr)
            sys.exit(1)

        if output_path:
            out = open(output_path, "w", encoding="utf-8")
        else:
            out = sys.stdout

        try:
            if fmt == "csv":
                from reflexa.eval.export import stream_csv
                async for chunk in stream_csv(db, batch_id):
                    out.write(chunk)
            else:
                from reflexa.eval.export import stream_jsonl
                async for chunk in stream_jsonl(db, batch_id):
                    out.write(chunk)
        finally:
            if output_path:
                out.close()
                print(f"Exported to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export evaluation results.")
    parser.add_argument("--batch-id", default=None, help="Eval batch ID to export")
    parser.add_argument(
        "--format",
        choices=["csv", "jsonl"],
        default="csv",
        help="Output format (default: csv)",
    )
    parser.add_argument("--output", default=None, metavar="FILE", help="Output file path (default: stdout)")
    parser.add_argument("--list-batches", action="store_true", help="List all eval batches and exit")
    args = parser.parse_args()

    if args.list_batches:
        asyncio.run(_list_batches())
        return

    if not args.batch_id:
        parser.error("--batch-id is required unless --list-batches is used")

    asyncio.run(_export(args.batch_id, args.format, args.output))


if __name__ == "__main__":
    main()
