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


async def set_rls_runtime_role(session: AsyncSession) -> None:
    # RLS policies are deliberately scoped to graphytion_runtime. Explicitly
    # assume that inherited role instead of relying on implicit membership.
    has_runtime_role = (
        await session.execute(
            text("""
                select exists (
                    select 1
                    from pg_roles r
                    where r.rolname='graphytion_runtime'
                      and pg_has_role(current_user,r.oid,'MEMBER')
                )
            """)
        )
    ).scalar_one()
    if not has_runtime_role:
        raise RuntimeError("Database session is not a member of graphytion_runtime")
    # Scope role elevation to the current transaction. This is required for
    # Supavisor transaction pooling and prevents role state leaking between requests.
    await session.execute(text("SET LOCAL ROLE graphytion_runtime"))


async def set_rls_subject(session: AsyncSession, user_id: str | None) -> None:
    if user_id is not None:
        await set_rls_runtime_role(session)

    # Supabase auth.uid() first reads request.jwt.claim.sub and falls back to
    # request.jwt.claims. Set both in the same transaction as the protected DML.
    # During dependency cleanup, clear session-level values after the transaction
    # has been rolled back so a pooled connection cannot retain a previous actor.
    is_local = user_id is not None
    await session.execute(
        text("""
            select
              set_config('request.jwt.claim.sub', :subject, :is_local),
              set_config('request.jwt.claim.role', :role, :is_local),
              set_config(
                'request.jwt.claims',
                case when :subject <> ''
                  then jsonb_build_object('sub', :subject, 'role', 'authenticated')::text
                  else ''
                end,
                :is_local
              )
        """),
        {
            "subject": user_id or "",
            "role": "authenticated" if user_id else "",
            "is_local": is_local,
        },
    )


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            try:
                await session.rollback()
                # A pooled connection must never retain the assumed runtime role
                # or a previous user's JWT claims after this request completes.
                await session.execute(text("RESET ROLE"))
                await set_rls_subject(session, None)
                await session.commit()
            except Exception:
                await session.rollback()
                try:
                    await session.execute(text("RESET ROLE"))
                    await session.commit()
                except Exception:
                    await session.rollback()
