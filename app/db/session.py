import logging
import ssl

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

logger = logging.getLogger(__name__)

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

db_url = settings.async_database_url
# Log URL mascherato (nasconde la password)
masked_url = db_url.split("@")[-1] if "@" in db_url else "NO @ FOUND"
logger.warning(f"DB ENGINE CONFIG: host={masked_url}, statement_cache_size=0, prepared_statement_cache_size=0, ssl=True")

engine = create_async_engine(
    db_url,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args={
        "ssl": ssl_context,
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
    },
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db():
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()
