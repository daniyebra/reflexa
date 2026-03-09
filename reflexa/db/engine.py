from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import event, text

from reflexa.config import settings
from reflexa.db.models import Base


def _apply_pragmas(dbapi_conn, _connection_record):
    """Set SQLite pragmas on every new connection."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute("PRAGMA journal_mode = WAL")
    cursor.execute("PRAGMA busy_timeout = 30000")
    cursor.close()


def build_engine(database_url: str | None = None):
    url = database_url or settings.database_url
    engine = create_async_engine(url, echo=False)
    # aiosqlite surfaces the raw DBAPI connection through the sync layer
    event.listen(engine.sync_engine, "connect", _apply_pragmas)
    return engine


engine = build_engine()

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db(eng=None) -> None:
    """Create all tables (idempotent — safe to call on startup)."""
    target = eng or engine
    async with target.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a DB session per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
