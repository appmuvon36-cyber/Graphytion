from __future__ import annotations

import json
import math
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings


OUTPUT_TOKEN_BUDGET = {
    "brief": 1800,
    "script": 2800,
    "storyboard": 6500,
    "scene": 2200,
}


async def reserve_ai_usage(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    project_id: UUID,
    run_id: UUID,
    stage: str,
    input_snapshot: dict[str, Any],
    idempotency_key: str,
) -> UUID:
    provider = settings.llm_default_provider.strip().lower()
    model = settings.gemini_model_key if provider == "gemini" else settings.llm_model_key
    price = (await db.execute(text("""
        select input_microusd_per_million,output_microusd_per_million
        from public.ai_model_prices
        where provider_key=:provider and model_key=:model and is_active=true and effective_at<=now()
        order by effective_at desc,created_at desc limit 1
    """), {"provider": provider, "model": model})).mappings().first()
    if price is None:
        raise HTTPException(status_code=503, detail={
            "code": "AI_MODEL_PRICE_NOT_CONFIGURED",
            "message": f"No active price-book entry is configured for {provider}/{model}.",
        })
    serialized = json.dumps(input_snapshot, ensure_ascii=False, sort_keys=True)
    estimated_input_tokens = max(1, math.ceil(len(serialized) / 4) + 400)
    estimated_output_tokens = OUTPUT_TOKEN_BUDGET.get(stage, 2000)
    estimated_microusd = math.ceil((
        estimated_input_tokens * int(price["input_microusd_per_million"])
        + estimated_output_tokens * int(price["output_microusd_per_million"])
    ) / 1_000_000)
    # Reserve 50% above the stage estimate; reconciliation always consumes the
    # provider-reported token cost and releases any unused reservation.
    reserve_amount = max(1, math.ceil(estimated_microusd * 1.5))
    reservation_id = await db.scalar(text("""
        select private.graphytion_reserve_quota(
          :workspace,:project,'creative_run',:run,:key,:amount,
          cast(:metadata as jsonb)
        )
    """), {
        "workspace": workspace_id, "project": project_id, "run": run_id,
        "key": "creative:" + idempotency_key, "amount": reserve_amount,
        "metadata": json.dumps({
            "stage": stage, "provider": provider, "model": model,
            "estimated_input_tokens": estimated_input_tokens,
            "estimated_output_tokens": estimated_output_tokens,
        }),
    })
    return UUID(str(reservation_id))


async def reconcile_ai_usage(db: AsyncSession, run_id: UUID) -> None:
    reservation_id = await db.scalar(text("""
        select id from public.quota_reservations
        where resource_type='creative_run' and resource_id=:run
    """), {"run": run_id})
    if reservation_id is None:
        return
    usage = (await db.execute(text("""
        select coalesce(sum(total_cost_microusd),0)::bigint actual_cost,
          count(*) filter(where cost_status='unpriced')::bigint unpriced_events,
          count(*)::bigint events
        from public.ai_usage_events where production_run_id=:run
    """), {"run": run_id})).mappings().one()
    if usage["unpriced_events"] or not usage["events"]:
        await db.execute(text("""
            select private.graphytion_release_quota(:reservation,:reason)
        """), {"reservation": reservation_id, "reason": "provider_usage_unpriced_or_missing"})
        return
    await db.execute(text("""
        select private.graphytion_reconcile_quota(:reservation,:actual,cast(:metadata as jsonb))
    """), {
        "reservation": reservation_id, "actual": int(usage["actual_cost"]),
        "metadata": json.dumps({"usage_events": int(usage["events"])}),
    })


async def release_ai_usage(db: AsyncSession, run_id: UUID, reason: str) -> None:
    reservation_id = await db.scalar(text("""
        select id from public.quota_reservations
        where resource_type='creative_run' and resource_id=:run
    """), {"run": run_id})
    if reservation_id is not None:
        await db.execute(text("""
            select private.graphytion_release_quota(:reservation,:reason)
        """), {"reservation": reservation_id, "reason": reason[:120]})


async def reserve_fixed_operation(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    project_id: UUID,
    resource_type: str,
    resource_id: UUID,
    operation_key: str,
    units: int,
    idempotency_key: str,
) -> UUID:
    if units < 1:
        raise HTTPException(status_code=422, detail="Quota usage units must be positive")
    price = (await db.execute(text("""
        select microusd_per_unit,unit_name from public.quota_operation_prices
        where operation_key=:operation and price_kind='quota' and is_active=true and effective_at<=now()
        order by effective_at desc,created_at desc limit 1
    """), {"operation": operation_key})).mappings().first()
    if price is None:
        raise HTTPException(status_code=503, detail={
            "code": "QUOTA_OPERATION_PRICE_NOT_CONFIGURED",
            "message": f"No active quota rate is configured for {operation_key}.",
        })
    amount = max(1, int(price["microusd_per_unit"]) * units)
    reservation_id = await db.scalar(text("""
        select private.graphytion_reserve_quota(
          :workspace,:project,:resource_type,:resource_id,:key,:amount,
          cast(:metadata as jsonb)
        )
    """), {
        "workspace": workspace_id, "project": project_id,
        "resource_type": resource_type, "resource_id": resource_id,
        "key": idempotency_key, "amount": amount,
        "metadata": json.dumps({"operation": operation_key, "units": units,
                                "unit_name": price["unit_name"],
                                "microusd_per_unit": int(price["microusd_per_unit"])}),
    })
    return UUID(str(reservation_id))


async def reconcile_fixed_operation(
    db: AsyncSession, *, resource_type: str, resource_id: UUID
) -> None:
    reservation = (await db.execute(text("""
        select id,reserved_microusd from public.quota_reservations
        where resource_type=:type and resource_id=:resource and status='reserved'
        order by created_at desc limit 1 for update
    """), {"type": resource_type, "resource": resource_id})).mappings().first()
    if reservation is None:
        return
    await db.execute(text("""
        select private.graphytion_reconcile_quota(:id,:amount,cast(:metadata as jsonb))
    """), {"id": reservation["id"], "amount": reservation["reserved_microusd"],
           "metadata": json.dumps({"billing_basis": "configured_operation_rate"})})


async def release_fixed_operation(
    db: AsyncSession, *, resource_type: str, resource_id: UUID, reason: str
) -> None:
    reservation = (await db.execute(text("""
        select id from public.quota_reservations
        where resource_type=:type and resource_id=:resource and status='reserved'
        order by created_at desc limit 1
    """), {"type": resource_type, "resource": resource_id})).scalar_one_or_none()
    if reservation is not None:
        await db.execute(text("""
            select private.graphytion_release_quota(:id,:reason)
        """), {"id": reservation, "reason": reason[:120]})


async def reverse_quota(
    db: AsyncSession, *, reservation_id: UUID, amount_microusd: int,
    idempotency_key: str, reason: str,
) -> None:
    await db.execute(text("""
        select private.graphytion_reverse_quota(:id,:amount,:key,:reason)
    """), {"id": reservation_id, "amount": amount_microusd,
           "key": idempotency_key, "reason": reason[:240]})
