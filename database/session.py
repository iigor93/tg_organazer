import logging
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import DB_MAX_OVERFLOW, DB_POOL_SIZE, DB_POOL_TIMEOUT, database_url


class Base(DeclarativeBase):
    pass


def get_database_url() -> str:
    return database_url


def create_db_engine():
    options = {"echo": False, "pool_pre_ping": True}
    if not database_url.startswith("sqlite"):
        if DB_POOL_SIZE < 1 or DB_MAX_OVERFLOW < 0 or DB_POOL_TIMEOUT <= 0:
            raise ValueError("Database pool limits must be positive; overflow may be zero.")
        options.update(pool_size=DB_POOL_SIZE, max_overflow=DB_MAX_OVERFLOW, pool_timeout=DB_POOL_TIMEOUT)
    return create_async_engine(database_url, **options)


engine = create_db_engine()
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


logger = logging.getLogger(__name__)


@asynccontextmanager
async def get_db_session():
    async with AsyncSessionLocal() as session:
        try:
            logger.info("get session")
            yield session
        except Exception:
            logger.exception("Err save to db")
            await session.rollback()
            raise
