"""
CLI — run an offline evaluation batch.

Usage:
    python scripts/run_eval.py [--judge-models gpt-4o-mini gpt-4o] [--notes "Run 1"] [--dry-run]

Dry-run mode estimates the number of LLM judge calls and approximate cost without
making any actual calls.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone


async def _count_unscored() -> int:
    from reflexa.db.engine import AsyncSessionLocal
    from reflexa.db import crud

    async with AsyncSessionLocal() as db:
        items = await crud.get_unscored_feedback_outputs(db)
        return len(items)


async def _run(judge_models: list[str], notes: str | None, dry_run: bool) -> None:
    from reflexa.db.engine import AsyncSessionLocal, init_db, engine
    from reflexa.db import crud
    from reflexa.config import settings
    from reflexa.llm.client import build_llm_client
    from reflexa.eval.judge import EVAL_DIMENSIONS

    await init_db(engine)

    n_items = await _count_unscored()
    n_judges = len(judge_models)
    n_dimensions = len(EVAL_DIMENSIONS)
    n_calls = n_items * n_judges * n_dimensions

    print(f"Unscored feedback outputs : {n_items}")
    print(f"Judge models              : {judge_models}")
    print(f"Dimensions                : {n_dimensions}")
    print(f"Total LLM judge calls     : {n_calls}")

    if dry_run:
        print("\n[dry-run] No calls will be made.")
        return

    if n_items == 0:
        print("No unscored outputs found. Exiting.")
        return

    llm_client = build_llm_client(settings)

    async with AsyncSessionLocal() as db:
        async with db.begin():
            unscored = await crud.get_unscored_feedback_outputs(db)
            fo_ids = [fo.id for fo in unscored]

            seed = int(datetime.now(timezone.utc).timestamp())
            batch_id_str = __import__("uuid").uuid4().__str__()
            batch = await crud.create_eval_batch(
                db,
                id=batch_id_str,
                judge_models=json.dumps(judge_models),
                notes=notes or f"CLI run, seed={seed}",
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            await crud.create_eval_items(
                db,
                eval_batch_id=batch_id_str,
                feedback_output_ids=fo_ids,
                seed=seed,
                created_at=datetime.now(timezone.utc).isoformat(),
            )

    print(f"\nEval batch created: {batch_id_str}")
    print("Running evaluation…")

    from reflexa.eval.harness import run_evaluation

    await run_evaluation(batch_id_str, llm_client)
    print("Done.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an offline evaluation batch.")
    parser.add_argument(
        "--judge-models",
        nargs="+",
        default=["mock"],
        metavar="MODEL",
        help="Judge model IDs (default: mock)",
    )
    parser.add_argument("--notes", default=None, help="Human annotation for this batch")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Estimate call count and cost without running",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.judge_models, args.notes, args.dry_run))


if __name__ == "__main__":
    main()
