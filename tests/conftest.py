"""
Shared pytest fixtures for Reflexa tests.

Provides:
- db_session  — async in-memory SQLite session (schema created fresh per test)
- mock_llm    — MockLLMClient bound to the same in-memory session
"""
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from reflexa.db.models import Base
from reflexa.llm.mock import MockLLMClient


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """Yield a fresh in-memory SQLite session with all tables created."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
def mock_llm() -> MockLLMClient:
    """Return a zero-failure MockLLMClient for use in pipeline / API tests."""
    return MockLLMClient()
