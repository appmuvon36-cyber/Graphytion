from __future__ import annotations

import json
from collections import defaultdict, deque
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthenticatedClaims, DbSession
from app.services.workspace_authorization import WorkspacePermissionResolver

router = APIRouter()
permissions = WorkspacePermissionResolver()
ChildType = Literal["agent_task", "media_generation", "audio_generation", "render_job"]


def _actor(claims: dict[str, Any]) -> UUID:
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(401, "Invalid authenticated subject") from exc


async def _run_scope(db: AsyncSession, run_id: UUID, actor: UUID, permission: str):
    row = (await db.execute(text("""
        select id,project_id,workspace_id,requested_by,status
        from public.production_runs where id=:run
    """), {"run": run_id})).mappings().first()
    if row is None:
        raise HTTPException(404, "Production run not found")
    await permissions.require_permission(
        session=db, user_id=str(actor), workspace_id=str(row["workspace_id"]), permission=permission
    )
    return row


class StepDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$")
    step_type: Literal[
        "creative", "agent", "media_generation", "asset_persistence", "voiceover",
        "audio_processing", "subtitle", "timeline", "composition", "render",
        "quality_check", "delivery"
    ]
    depends_on: list[str] = Field(default_factory=list, max_length=40)
    input_refs: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = False
    max_attempts: int = Field(default=3, ge=1, le=10)
    timeout_seconds: int = Field(default=1800, ge=1, le=86400)


class WorkflowCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    steps: list[StepDefinition] = Field(min_length=1, max_length=60)


class ChildAttach(BaseModel):
    model_config = ConfigDict(extra="forbid")
    child_type: ChildType
    child_job_id: UUID


def _validate_dag(steps: list[StepDefinition]) -> None:
    by_key = {step.key: step for step in steps}
    if len(by_key) != len(steps):
        raise HTTPException(422, "Workflow step keys must be unique")
    indegree = {key: 0 for key in by_key}
    children: dict[str, list[str]] = defaultdict(list)
    for step in steps:
        if len(set(step.depends_on)) != len(step.depends_on):
            raise HTTPException(422, f"Duplicate dependency in step {step.key}")
        for parent in step.depends_on:
            if parent not in by_key:
                raise HTTPException(422, f"Unknown dependency {parent} in step {step.key}")
            if parent == step.key:
                raise HTTPException(422, "A workflow step cannot depend on itself")
            indegree[step.key] += 1
            children[parent].append(step.key)
    ready = deque(key for key, degree in indegree.items() if degree == 0)
    visited = 0
    while ready:
        current = ready.popleft()
        visited += 1
        for child in children[current]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if visited != len(steps):
        raise HTTPException(422, "Workflow dependency graph contains a cycle")


@router.post("/creative-runs/{run_id}/workflow", status_code=201)
async def create_production_workflow(
    run_id: UUID, payload: WorkflowCreate, claims: AuthenticatedClaims,
    request: Request, db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    run = await _run_scope(db, run_id, actor, "project.update")
    _validate_dag(payload.steps)
    existing = (await db.execute(text("""
        select s.id,s.step_key,s.step_type,s.requires_approval,
          coalesce(array_agg(p.step_key order by p.step_key) filter(where p.step_key is not null),'{}'::text[]) depends_on
        from public.production_run_steps s
        left join public.production_run_step_dependencies d on d.step_id=s.id
        left join public.production_run_steps p on p.id=d.depends_on_step_id
        where s.production_run_id=:run group by s.id order by s.created_at
    """), {"run": run_id})).mappings().all()
    if existing:
        expected = {(s.key, s.step_type, s.requires_approval, tuple(sorted(s.depends_on))) for s in payload.steps}
        actual = {(r["step_key"], r["step_type"], r["requires_approval"], tuple(r["depends_on"])) for r in existing}
        if expected != actual:
            raise HTTPException(409, "A workflow is already defined for this Production Run")
        await db.execute(text("select private.graphytion_sync_production_run(:run)"), {"run": run_id})
        await db.commit()
        return {"data": {"run_id": str(run_id), "steps": len(existing), "replayed": True}}

    ids: dict[str, UUID] = {}
    for step in payload.steps:
        row = (await db.execute(text("""
            insert into public.production_run_steps(
              production_run_id,workspace_id,project_id,step_key,step_type,status,
              input_refs,config,requires_approval,idempotency_key,max_attempts,timeout_seconds
            ) values(
              :run,:workspace,:project,:key,:type,
              case when cardinality(cast(:deps as text[]))=0
                then case when :approval then 'waiting_approval' else 'ready' end
                else 'pending' end,
              cast(:inputs as jsonb),cast(:config as jsonb),:approval,
              :idem,:attempts,:timeout
            ) returning id
        """), {
            "run": run_id, "workspace": run["workspace_id"], "project": run["project_id"],
            "key": step.key, "type": step.step_type, "deps": step.depends_on,
            "approval": step.requires_approval, "inputs": json.dumps(step.input_refs),
            "config": json.dumps(step.config), "idem": f"{run_id}:{step.key}",
            "attempts": step.max_attempts, "timeout": step.timeout_seconds,
        })).scalar_one()
        ids[step.key] = row

    for step in payload.steps:
        for parent in step.depends_on:
            await db.execute(text("""
                insert into public.production_run_step_dependencies(
                  production_run_id,workspace_id,project_id,step_id,depends_on_step_id
                ) values(:run,:workspace,:project,:step,:parent)
            """), {
                "run": run_id, "workspace": run["workspace_id"], "project": run["project_id"],
                "step": ids[step.key], "parent": ids[parent],
            })
    await db.execute(text("""
        insert into public.workflow_events(production_run_id,event_type,event_payload,sequence_number)
        values(:run,'workflow.created',cast(:payload as jsonb),
          (select coalesce(max(sequence_number),0)+1 from public.workflow_events where production_run_id=:run))
    """), {"run": run_id, "payload": json.dumps({"step_count": len(payload.steps), "step_keys": list(ids)})})
    summary = await db.scalar(text("select private.graphytion_sync_production_run(:run)"), {"run": run_id})
    await db.commit()
    return {"data": {"run_id": str(run_id), "steps": len(ids), "state": summary, "replayed": False}}


@router.get("/creative-runs/{run_id}/workflow")
async def get_production_workflow(
    run_id: UUID, claims: AuthenticatedClaims, db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _run_scope(db, run_id, actor, "project.read")
    summary = await db.scalar(text("select private.graphytion_sync_production_run(:run)"), {"run": run_id})
    steps = (await db.execute(text("""
        select s.id,s.step_key,s.step_type,s.status,s.input_refs,s.output_refs,s.config,
          s.requires_approval,s.approved_by,s.approved_at,s.attempt_count,s.max_attempts,
          s.available_at,s.timeout_seconds,s.started_at,s.completed_at,s.error_code,
          s.error_message_safe,s.child_job_type,s.child_job_id,s.created_at,s.updated_at,
          coalesce(jsonb_agg(jsonb_build_object('step_id',d.depends_on_step_id,'step_key',p.step_key))
            filter(where d.depends_on_step_id is not null),'[]'::jsonb) dependencies,
          coalesce((select jsonb_agg(jsonb_build_object('asset_id',b.asset_id,'usage_role',b.usage_role))
            from public.production_run_step_assets b where b.step_id=s.id),'[]'::jsonb) assets
        from public.production_run_steps s
        left join public.production_run_step_dependencies d on d.step_id=s.id
        left join public.production_run_steps p on p.id=d.depends_on_step_id
        where s.production_run_id=:run
        group by s.id order by s.created_at,s.step_key
    """), {"run": run_id})).mappings().all()
    events = (await db.execute(text("""
        select event_type,event_payload,sequence_number,created_at
        from public.workflow_events where production_run_id=:run order by sequence_number
    """), {"run": run_id})).mappings().all()
    await db.commit()
    return {"data": {"run_id": str(run_id), "summary": summary,
                     "steps": [dict(row) for row in steps], "events": [dict(row) for row in events]}}


@router.post("/creative-runs/{run_id}/steps/{step_id}/approve")
async def approve_production_step(
    run_id: UUID, step_id: UUID, request: Request, claims: AuthenticatedClaims,
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    run = await _run_scope(db, run_id, actor, "project.update")
    row = (await db.execute(text("""
        update public.production_run_steps
        set status='ready',approved_by=:actor,approved_at=now(),updated_at=now()
        where id=:step and production_run_id=:run and workspace_id=:workspace
          and requires_approval and status='waiting_approval'
        returning id,step_key
    """), {"actor": actor, "step": step_id, "run": run_id, "workspace": run["workspace_id"]})).mappings().first()
    if row is None:
        raise HTTPException(409, "Step is not waiting for approval")
    await db.execute(text("""
        insert into public.workflow_events(production_run_id,event_type,event_payload,sequence_number)
        values(:run,'step.approved',cast(:payload as jsonb),
          (select coalesce(max(sequence_number),0)+1 from public.workflow_events where production_run_id=:run))
    """), {"run": run_id, "payload": json.dumps({"step_id": str(step_id), "step_key": row["step_key"], "approved_by": str(actor)})})
    await db.execute(text("select private.graphytion_sync_production_run(:run)"), {"run": run_id})
    await db.commit()
    return {"data": {"step_id": str(step_id), "status": "ready"}}


@router.post("/creative-runs/{run_id}/steps/{step_id}/attach-child")
async def attach_production_child_job(
    run_id: UUID, step_id: UUID, payload: ChildAttach, claims: AuthenticatedClaims,
    request: Request, db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    run = await _run_scope(db, run_id, actor, "project.update")
    step = (await db.execute(text("""
        select id,step_type,status,child_job_id from public.production_run_steps
        where id=:step and production_run_id=:run and workspace_id=:workspace for update
    """), {"step": step_id, "run": run_id, "workspace": run["workspace_id"]})).mappings().first()
    if step is None:
        raise HTTPException(404, "Production step not found")
    if step["child_job_id"] and step["child_job_id"] != payload.child_job_id:
        raise HTTPException(409, "Step already owns a different child job")
    table, id_col, owner_col = {
        "agent_task": ("agent_tasks", "id", "production_run_id"),
        "media_generation": ("media_generation_jobs", "id", "requested_by"),
        "audio_generation": ("audio_generations", "id", "requested_by"),
        "render_job": ("render_jobs", "id", "requested_by"),
    }[payload.child_type]
    if payload.child_type == "agent_task":
        child = (await db.execute(text("""
            select id,status,production_run_id from public.agent_tasks
            where id=:child and production_run_id=:run for update
        """), {"child": payload.child_job_id, "run": run_id})).mappings().first()
        if child is None:
            raise HTTPException(404, "Agent task does not belong to this Production Run")
        await db.execute(text("""
            update public.agent_tasks set parent_step_id=:step
            where id=:child and production_run_id=:run
        """), {"step": step_id, "child": payload.child_job_id, "run": run_id})
    else:
        child = (await db.execute(text(f"""
            select id,status,production_run_id from public.{table}
            where id=:child and project_id=:project and workspace_id=:workspace
              and requested_by=:actor for update
        """), {"child": payload.child_job_id, "project": run["project_id"],
               "workspace": run["workspace_id"], "actor": actor})).mappings().first()
        if child is None:
            raise HTTPException(404, "Child job not found in this project")
        if child["production_run_id"] not in (None, run_id):
            raise HTTPException(409, "Child job already belongs to another Production Run")
        await db.execute(text(f"""
            update public.{table} set production_run_id=:run,parent_step_id=:step
            where id=:child
        """), {"run": run_id, "step": step_id, "child": payload.child_job_id})
    await db.execute(text("""
        update public.production_run_steps
        set child_job_type=:type,child_job_id=:child,status='running',
            started_at=coalesce(started_at,now()),updated_at=now()
        where id=:step
    """), {"type": payload.child_type, "child": payload.child_job_id, "step": step_id})
    summary = await db.scalar(text("select private.graphytion_sync_production_run(:run)"), {"run": run_id})
    await db.commit()
    return {"data": {"step_id": str(step_id), "child_job_type": payload.child_type,
                     "child_job_id": str(payload.child_job_id), "state": summary}}


@router.post("/creative-runs/{run_id}/steps/{step_id}/retry")
async def retry_production_step(
    run_id: UUID, step_id: UUID, claims: AuthenticatedClaims, db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    run = await _run_scope(db, run_id, actor, "project.update")
    row = (await db.execute(text("""
        update public.production_run_steps
        set status='ready',attempt_count=attempt_count+1,available_at=now(),
            error_code=null,error_message_safe=null,started_at=null,completed_at=null,updated_at=now()
        where id=:step and production_run_id=:run and workspace_id=:workspace
          and status='failed' and child_job_id is null and attempt_count<max_attempts
        returning id,step_key,attempt_count
    """), {"step": step_id, "run": run_id, "workspace": run["workspace_id"]})).mappings().first()
    if row is None:
        raise HTTPException(409, "Only failed orchestration-only steps can be retried here; retry an attached child job through its own API to avoid duplicate provider operations")
    await db.execute(text("""
        insert into public.workflow_events(production_run_id,event_type,event_payload,sequence_number)
        values(:run,'step.retry_scheduled',cast(:payload as jsonb),
          (select coalesce(max(sequence_number),0)+1 from public.workflow_events where production_run_id=:run))
    """), {"run": run_id, "payload": json.dumps({"step_id": str(step_id), "attempt": row["attempt_count"]})})
    await db.commit()
    return {"data": {"step_id": str(step_id), "status": "ready", "attempt_count": row["attempt_count"]}}


@router.post("/creative-runs/{run_id}/cancel-workflow")
async def cancel_production_workflow(
    run_id: UUID, request: Request, claims: AuthenticatedClaims, db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    run = await _run_scope(db, run_id, actor, "project.update")
    await db.execute(text("""
        update public.production_run_steps set status='cancelled',completed_at=now(),updated_at=now()
        where production_run_id=:run and status in ('pending','ready','waiting_approval')
    """), {"run": run_id})
    # Cancel queued children immediately; request cooperative cancellation for
    # provider/render operations already in flight. Workers retain lease ownership.
    await db.execute(text("""
        update public.media_generation_jobs set status='cancelled',completed_at=now(),updated_at=now()
        where production_run_id=:run and status='queued'
    """), {"run": run_id})
    await db.execute(text("""
        update public.media_generation_jobs set status='cancel_requested',updated_at=now()
        where production_run_id=:run and status='processing'
    """), {"run": run_id})
    await db.execute(text("""
        update public.audio_generations set status='cancelled',completed_at=now(),updated_at=now()
        where production_run_id=:run and status='queued'
    """), {"run": run_id})
    await db.execute(text("""
        update public.render_jobs set status='cancelled',completed_at=now(),worker_id=null,lease_expires_at=null
        where production_run_id=:run and status='queued'
    """), {"run": run_id})
    await db.execute(text("""
        update public.render_jobs set status='cancel_requested',updated_at=now()
        where production_run_id=:run and status='rendering'
    """), {"run": run_id})
    await db.execute(text("""
        update public.agent_tasks set status='cancelled',completed_at=now(),worker_id=null,lease_expires_at=null
        where production_run_id=:run and status in ('queued','pending','retry_wait')
    """), {"run": run_id})
    await db.execute(text("""
        update public.production_runs set status='cancel_requested',cancel_requested_at=coalesce(cancel_requested_at,now())
        where id=:run and status not in ('completed','failed','cancelled')
    """), {"run": run_id})
    await db.execute(text("""
        insert into public.workflow_events(production_run_id,event_type,event_payload,sequence_number)
        values(:run,'workflow.cancel_requested',cast(:payload as jsonb),
          (select coalesce(max(sequence_number),0)+1 from public.workflow_events where production_run_id=:run))
    """), {"run": run_id, "payload": json.dumps({"requested_by": str(actor)})})
    await db.execute(text("select private.graphytion_sync_production_run(:run)"), {"run": run_id})
    await db.commit()
    return {"data": {"run_id": str(run_id), "status": "cancel_requested"}}


class StepAssetBind(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: UUID
    usage_role: Literal["input", "reference", "source", "preview"] = "input"


@router.post("/creative-runs/{run_id}/steps/{step_id}/assets", status_code=201)
async def bind_production_step_asset(
    run_id: UUID, step_id: UUID, payload: StepAssetBind, claims: AuthenticatedClaims,
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    run = await _run_scope(db, run_id, actor, "project.update")
    step = (await db.execute(text("""
        select id,status from public.production_run_steps
        where id=:step and production_run_id=:run and workspace_id=:workspace
    """), {"step": step_id, "run": run_id, "workspace": run["workspace_id"]})).mappings().first()
    if step is None:
        raise HTTPException(404, "Production step not found")
    if step["status"] not in {"ready", "running"}:
        raise HTTPException(409, "Assets can only be bound to a ready or running step")
    asset_ok = await db.scalar(text("""
        select exists(select 1 from public.project_assets
        where id=:asset and workspace_id=:workspace and project_id=:project
          and status='active' and deleted_at is null)
    """), {"asset": payload.asset_id, "workspace": run["workspace_id"], "project": run["project_id"]})
    if not asset_ok:
        raise HTTPException(404, "Active project asset not found")
    row = (await db.execute(text("""
        insert into public.production_run_step_assets(
          production_run_id,workspace_id,project_id,step_id,asset_id,usage_role,created_by
        ) values(:run,:workspace,:project,:step,:asset,:role,:actor)
        on conflict(step_id,asset_id,usage_role) do update set created_by=excluded.created_by
        returning id,asset_id,usage_role,created_at
    """), {"run": run_id, "workspace": run["workspace_id"], "project": run["project_id"],
           "step": step_id, "asset": payload.asset_id, "role": payload.usage_role, "actor": actor})).mappings().one()
    await db.commit()
    return {"data": dict(row)}


class StepComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    output_refs: dict[str, Any] = Field(default_factory=dict)


@router.post("/creative-runs/{run_id}/steps/{step_id}/complete")
async def complete_production_step(
    run_id: UUID, step_id: UUID, payload: StepComplete, claims: AuthenticatedClaims,
    request: Request, db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    run = await _run_scope(db, run_id, actor, "project.update")
    ready = await db.scalar(text("""
        select not exists (
          select 1 from public.production_run_step_dependencies d
          join public.production_run_steps p on p.id=d.depends_on_step_id
          where d.step_id=:step and p.status<>'completed'
        )
    """), {"step": step_id})
    if not ready:
        raise HTTPException(409, "Step dependencies are not complete")
    row = (await db.execute(text("""
        update public.production_run_steps
        set status='completed',output_refs=cast(:outputs as jsonb),
            completed_at=now(),updated_at=now()
        where id=:step and production_run_id=:run and workspace_id=:workspace
          and status in ('ready','running') and child_job_id is null
        returning id,step_key
    """), {"outputs": json.dumps(payload.output_refs), "step": step_id,
           "run": run_id, "workspace": run["workspace_id"]})).mappings().first()
    if row is None:
        raise HTTPException(409, "Only an active step without a child job can be completed manually")
    await db.execute(text("""
        insert into public.workflow_events(production_run_id,event_type,event_payload,sequence_number)
        values(:run,'step.completed',cast(:payload as jsonb),
          (select coalesce(max(sequence_number),0)+1 from public.workflow_events where production_run_id=:run))
    """), {"run": run_id, "payload": json.dumps({"step_id": str(step_id), "step_key": row["step_key"], "completed_by": str(actor), "output_refs": payload.output_refs})})
    summary = await db.scalar(text("select private.graphytion_sync_production_run(:run)"), {"run": run_id})
    await db.commit()
    return {"data": {"step_id": str(step_id), "status": "completed", "state": summary}}
