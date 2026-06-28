from sqlmodel import SQLModel
from minio import Minio
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from redis.asyncio import from_url as redis_from_url
from config import settings
from typing import Final, AsyncGenerator


engine: Final = create_async_engine(settings.DATABASE_URL, echo=True)
redis_client: Final = redis_from_url(settings.REDIS_URL, decode_response=True)
MINIO_BUCKET_NAME: Final[str] = settings.MINIO_BUCKET_NAME


AsyncSessionLocal: Final[async_sessionmaker[AsyncSession]] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def create_db_and_tables():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


minio_client: Final = Minio(
    settings.MINIO_ENDPOINT,
    access_key=settings.MINIO_ROOT_USER,
    secret_key=settings.MINIO_ROOT_PASSWORD,
    secure=False,
)
