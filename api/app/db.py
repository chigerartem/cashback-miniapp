from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


# pool_recycle=180: пересоздаём соединение, если оно старше 3 минут. docker-bridge
# рвёт idle-TCP за несколько минут, и без этого первый запрос после простоя ловит
# мёртвый коннект через TCP-таймаут (~7s холодного старта Mini App). pool_pre_ping —
# вторая страховка (пинг перед использованием). Пул держится тёплым healthcheck'ом
# /health (docker бьёт каждые 30s).
engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=180,
    future=True,
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
