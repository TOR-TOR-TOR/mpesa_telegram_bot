"""
database/__init__.py — Database engine and session factory.
Import get_session anywhere you need a DB connection.
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from database.models import Base
import config

engine = create_async_engine(config.DATABASE_URL, echo=False)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def init_db():
    """Create all tables if they don't exist. Called once on startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    """Yield a database session. Use as a dependency or context manager."""
    async with AsyncSessionLocal() as session:
        yield session