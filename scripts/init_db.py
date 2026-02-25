"""
One-time (idempotent) database initialisation script.

Usage:
    python scripts/init_db.py
    python scripts/init_db.py --db-url sqlite+aiosqlite:///custom.db
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Ensure the repo root is on sys.path when run directly.
sys.path.insert(0, str(Path(__file__).parent.parent))

from reflexa.db.engine import build_engine, init_db  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)


async def main(db_url: str | None) -> None:
    engine = build_engine(db_url)
    await init_db(engine)
    await engine.dispose()
    log.info("Database initialised successfully.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Initialise the Reflexa SQLite database.")
    parser.add_argument(
        "--db-url",
        default=None,
        help="SQLAlchemy async database URL (default: from config / .env)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.db_url))
