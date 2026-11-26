from collections.abc import AsyncGenerator
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

_database_url = settings.database_url_value
_database_host = urlparse(_database_url).hostname or ""
_is_supavisor_pooler = _database_host.endswith(".pooler.supabase.com")
_connect_args: dict[str, Any] = {"server_settings": {"application_name": "graphytion-api"}}
if _is_supavisor_pooler:
    _connect_args["prepared_statement_cache_size"] = 0

engine = create_async_engine(
    _database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    connect_args=_connect_args,
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def set_rls_subject(session: AsyncSession, user_id: str | None) -> None:
    await session.execute(
        text("""
            select
              set_config('request.jwt.claim.sub', :subject, false),
              set_config('request.jwt.claim.role', :role, false)
        """),
        {"subject": user_id or "", "role": "authenticated" if user_id else ""},
    )


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            try:
                await session.rollback()
                await set_rls_subject(session, None)
                await session.commit()
            except Exception:
                await session.rollback()
