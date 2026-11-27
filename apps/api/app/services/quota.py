from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def release_fixed_operation(
    db: AsyncSession, *, resource_type: str, resource_id: UUID, reason: str
) -> None:
    """Release a pre-existing legacy hold; personal Graphytion creates no new holds."""
    reservation = (
        await db.execute(
            text("""
                select id from public.quota_reservations
                where resource_type=:type and resource_id=:resource and status='reserved'
                order by created_at desc limit 1
            """),
            {"type": resource_type, "resource": resource_id},
        )
    ).scalar_one_or_none()
    if reservation is not None:
        await db.execute(
            text("select private.graphytion_release_quota(:id,:reason)"),
            {"id": reservation, "reason": reason[:120]},
        )
