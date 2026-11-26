import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthenticatedClaims, DbSession
from app.services.workspace_authorization import WorkspacePermissionResolver
from app.services.creative_pipeline import creative_pipeline

router = APIRouter()
permissions = WorkspacePermissionResolver()


def _actor(claims: dict[str, Any]) -> UUID:
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid authenticated subject") from exc


async def _project_scope(db: AsyncSession, project_id: UUID, actor: UUID, permission: str) -> UUID:
    row = (
        await db.execute(
            text("""
                select workspace_id from public.video_projects
                where id=:project_id and status <> 'deleted'
            """),
            {"project_id": project_id},
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await permissions.require_permission(
        session=db,
        user_id=str(actor),
        workspace_id=str(row),
        permission=permission,
    )
    return row


async def _audit(
    db: AsyncSession,
    request: Request,
    actor: UUID,
    workspace_id: UUID,
    action: str,
    resource_type: str,
    resource_id: UUID,
) -> None:
    await db.execute(
        text("""
            insert into public.audit_logs(
                actor_user_id, workspace_id, action, resource_type, resource_id, request_id
            ) values (:actor,:workspace,:action,:resource_type,:resource_id,:request_id)
        """),
        {
            "actor": actor,
            "workspace": workspace_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "request_id": getattr(request.state, "request_id", None),
        },
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, (UUID, date, datetime)):
        return value.isoformat() if isinstance(value, (date, datetime)) else str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _snapshot_hash(value: dict[str, Any]) -> str:
    canonical = json.dumps(_json_safe(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _record_version(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    project_id: UUID,
    artifact_type: str,
    artifact_id: UUID,
    version: int,
    actor: UUID,
    snapshot: dict[str, Any],
    summary: str,
) -> None:
    await db.execute(
        text("""
            insert into public.artifact_versions(
                workspace_id, project_id, artifact_type, artifact_id, version,
                content_hash, created_by, change_summary, snapshot
            ) values (
                :workspace,:project,:type,:artifact,:version,:hash,:actor,:summary,
                cast(:snapshot as jsonb)
            )
        """),
        {
            "workspace": workspace_id,
            "project": project_id,
            "type": artifact_type,
            "artifact": artifact_id,
            "version": version,
            "hash": _snapshot_hash(snapshot),
            "actor": actor,
            "summary": summary,
            "snapshot": json.dumps(_json_safe(snapshot), ensure_ascii=False),
        },
    )


class BriefCreate(BaseModel):
    input_prompt: str = Field(min_length=1, max_length=20000)
    normalized_brief: dict[str, Any]
    source_references: list[dict[str, Any]] = Field(default_factory=list)


class ScriptCreate(BaseModel):
    brief_id: UUID | None = None
    language: str = Field(min_length=2, max_length=16)
    title: str = Field(min_length=1, max_length=240)
    hook: str | None = Field(default=None, max_length=2000)
    body: dict[str, Any]
    cta: str | None = Field(default=None, max_length=2000)
    estimated_duration_ms: int | None = Field(default=None, gt=0)
    word_count: int | None = Field(default=None, ge=0)


class ScriptUpdate(BaseModel):
    language: str | None = Field(default=None, min_length=2, max_length=16)
    title: str | None = Field(default=None, min_length=1, max_length=240)
    hook: str | None = Field(default=None, max_length=2000)
    body: dict[str, Any] | None = None
    cta: str | None = Field(default=None, max_length=2000)
    estimated_duration_ms: int | None = Field(default=None, gt=0)
    word_count: int | None = Field(default=None, ge=0)


class SceneInput(BaseModel):
    scene_index: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=240)
    purpose: str | None = None
    narration_text: str | None = None
    duration_ms: int = Field(gt=0)
    visual_direction: dict[str, Any] = Field(default_factory=dict)
    transition_in: str | None = None
    transition_out: str | None = None
    motion_plan: dict[str, Any] = Field(default_factory=dict)
    asset_requirements: list[dict[str, Any]] = Field(default_factory=list)


class StoryboardCreate(BaseModel):
    script_id: UUID
    global_visual_direction: dict[str, Any] = Field(default_factory=dict)
    scenes: list[SceneInput] = Field(min_length=1, max_length=100)


class SceneUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    purpose: str | None = None
    narration_text: str | None = None
    duration_ms: int | None = Field(default=None, gt=0)
    visual_direction: dict[str, Any] | None = None
    transition_in: str | None = None
    transition_out: str | None = None
    motion_plan: dict[str, Any] | None = None
    asset_requirements: list[dict[str, Any]] | None = None


@router.get("/projects/{project_id}/briefs")
async def list_briefs(project_id: UUID, claims: AuthenticatedClaims, db: AsyncSession = DbSession):
    actor = _actor(claims)
    await _project_scope(db, project_id, actor, "project.read")
    rows = (
        await db.execute(
            text("select * from public.creative_briefs where project_id=:project order by version desc"),
            {"project": project_id},
        )
    ).mappings().all()
    return {"data": [dict(row) for row in rows]}


@router.post("/projects/{project_id}/briefs", status_code=201)
async def create_brief(
    project_id: UUID, payload: BriefCreate, request: Request,
    claims: AuthenticatedClaims, db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    workspace_id = await _project_scope(db, project_id, actor, "project.update")
    version = (await db.execute(
        text("select coalesce(max(version),0)+1 from public.creative_briefs where project_id=:project"),
        {"project": project_id},
    )).scalar_one()
    row = (await db.execute(
        text("""
            insert into public.creative_briefs(
                workspace_id,project_id,version,input_prompt,normalized_brief,
                source_references,created_by
            ) values (:workspace,:project,:version,:prompt,cast(:brief as jsonb),
                      cast(:sources as jsonb),:actor) returning *
        """),
        {
            "workspace": workspace_id, "project": project_id, "version": version,
            "prompt": payload.input_prompt.strip(),
            "brief": json.dumps(payload.normalized_brief, ensure_ascii=False),
            "sources": json.dumps(payload.source_references, ensure_ascii=False), "actor": actor,
        },
    )).mappings().one()
    snapshot = _json_safe(dict(row))
    await _record_version(db, workspace_id=workspace_id, project_id=project_id,
        artifact_type="creative_brief", artifact_id=row["id"], version=version,
        actor=actor, snapshot=snapshot,
        summary="Creative brief created")
    await _audit(db, request, actor, workspace_id, "creative_brief.created", "creative_brief", row["id"])
    await db.commit()
    return {"data": dict(row)}


@router.post("/projects/{project_id}/briefs/{brief_id}/approve")
async def approve_brief(
    project_id: UUID, brief_id: UUID, request: Request,
    claims: AuthenticatedClaims, db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    workspace_id = await _project_scope(db, project_id, actor, "project.update")
    row = (await db.execute(
        text("""
            update public.creative_briefs set status='approved', approved_by=:actor,
                approved_at=now()
            where id=:brief and project_id=:project and workspace_id=:workspace
            returning *
        """),
        {"actor": actor, "brief": brief_id, "project": project_id, "workspace": workspace_id},
    )).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Creative brief not found")
    await _audit(db, request, actor, workspace_id, "creative_brief.approved", "creative_brief", brief_id)
    await db.commit()
    return {"data": dict(row)}


@router.get("/projects/{project_id}/scripts")
async def list_scripts(project_id: UUID, claims: AuthenticatedClaims, db: AsyncSession = DbSession):
    actor = _actor(claims)
    await _project_scope(db, project_id, actor, "project.read")
    rows = (await db.execute(
        text("select * from public.video_scripts where project_id=:project order by version desc"),
        {"project": project_id},
    )).mappings().all()
    return {"data": [dict(row) for row in rows]}


@router.post("/projects/{project_id}/scripts", status_code=201)
async def create_script(
    project_id: UUID, payload: ScriptCreate, request: Request,
    claims: AuthenticatedClaims, db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    workspace_id = await _project_scope(db, project_id, actor, "project.update")
    if payload.brief_id:
        exists = (await db.execute(text("""
            select 1 from public.creative_briefs
            where id=:brief and project_id=:project and workspace_id=:workspace
        """), {"brief": payload.brief_id, "project": project_id, "workspace": workspace_id})).scalar_one_or_none()
        if not exists:
            raise HTTPException(status_code=404, detail="Creative brief not found in this project")
    version = (await db.execute(
        text("select coalesce(max(version),0)+1 from public.video_scripts where project_id=:project"),
        {"project": project_id},
    )).scalar_one()
    row = (await db.execute(text("""
        insert into public.video_scripts(
            workspace_id,project_id,brief_id,version,language,title,hook,body,cta,
            estimated_duration_ms,word_count,created_by
        ) values (:workspace,:project,:brief,:version,:language,:title,:hook,
                  cast(:body as jsonb),:cta,:duration,:words,:actor) returning *
    """), {
        "workspace": workspace_id, "project": project_id, "brief": payload.brief_id,
        "version": version, "language": payload.language, "title": payload.title.strip(),
        "hook": payload.hook, "body": json.dumps(payload.body, ensure_ascii=False),
        "cta": payload.cta, "duration": payload.estimated_duration_ms,
        "words": payload.word_count, "actor": actor,
    })).mappings().one()
    snapshot = _json_safe(dict(row))
    await _record_version(db, workspace_id=workspace_id, project_id=project_id,
        artifact_type="video_script", artifact_id=row["id"], version=version,
        actor=actor, snapshot=snapshot, summary="Script created")
    await _audit(db, request, actor, workspace_id, "video_script.created", "video_script", row["id"])
    await db.commit()
    return {"data": dict(row)}


@router.patch("/projects/{project_id}/scripts/{script_id}")
async def update_script(
    project_id: UUID, script_id: UUID, payload: ScriptUpdate, request: Request,
    claims: AuthenticatedClaims, db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    workspace_id = await _project_scope(db, project_id, actor, "project.update")
    current = (await db.execute(text("""
        select * from public.video_scripts
        where id=:script and project_id=:project and workspace_id=:workspace
    """), {"script": script_id, "project": project_id, "workspace": workspace_id})).mappings().first()
    if current is None:
        raise HTTPException(status_code=404, detail="Script not found")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return {"data": dict(current)}
    merged = dict(current)
    merged.update(changes)
    row = (await db.execute(text("""
        update public.video_scripts set language=:language,title=:title,hook=:hook,
            body=cast(:body as jsonb),cta=:cta,estimated_duration_ms=:duration,
            word_count=:words,status='draft'
        where id=:script and project_id=:project and workspace_id=:workspace returning *
    """), {
        "language": merged["language"], "title": merged["title"], "hook": merged["hook"],
        "body": json.dumps(merged["body"], ensure_ascii=False), "cta": merged["cta"],
        "duration": merged["estimated_duration_ms"], "words": merged["word_count"],
        "script": script_id, "project": project_id, "workspace": workspace_id,
    })).mappings().one()
    version = (await db.execute(text("""
        select coalesce(max(version),0)+1 from public.artifact_versions
        where project_id=:project and artifact_type='video_script' and artifact_id=:script
    """), {"project": project_id, "script": script_id})).scalar_one()
    snapshot = {k: str(v) if isinstance(v, UUID) else v for k,v in dict(row).items()}
    await _record_version(db, workspace_id=workspace_id, project_id=project_id,
        artifact_type="video_script", artifact_id=script_id, version=version,
        actor=actor, snapshot=snapshot, summary="Script revised")
    await _audit(db, request, actor, workspace_id, "video_script.updated", "video_script", script_id)
    await db.commit()
    return {"data": dict(row), "version": version}


@router.post("/projects/{project_id}/scripts/{script_id}/approve")
async def approve_script(
    project_id: UUID, script_id: UUID, request: Request,
    claims: AuthenticatedClaims, db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    workspace_id = await _project_scope(db, project_id, actor, "project.update")
    row = (await db.execute(text("""
        update public.video_scripts set status='approved'
        where id=:script and project_id=:project and workspace_id=:workspace
        returning *
    """), {"script": script_id, "project": project_id, "workspace": workspace_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Script not found")
    await _audit(db, request, actor, workspace_id, "video_script.approved", "video_script", script_id)
    await db.commit()
    return {"data": dict(row)}


@router.get("/projects/{project_id}/storyboards")
async def list_storyboards(project_id: UUID, claims: AuthenticatedClaims, db: AsyncSession = DbSession):
    actor = _actor(claims)
    await _project_scope(db, project_id, actor, "project.read")
    rows = (await db.execute(text("""
        select b.*, coalesce(jsonb_agg(to_jsonb(s) order by s.scene_index)
          filter (where s.id is not null),'[]'::jsonb) as scenes
        from public.storyboards b
        left join public.storyboard_scenes s on s.storyboard_id=b.id
        where b.project_id=:project
        group by b.id order by b.version desc
    """), {"project": project_id})).mappings().all()
    return {"data": [dict(row) for row in rows]}


@router.post("/projects/{project_id}/storyboards", status_code=201)
async def create_storyboard(
    project_id: UUID, payload: StoryboardCreate, request: Request,
    claims: AuthenticatedClaims, db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    workspace_id = await _project_scope(db, project_id, actor, "project.update")
    script_exists = (await db.execute(text("""
        select 1 from public.video_scripts
        where id=:script and project_id=:project and workspace_id=:workspace and status='approved'
    """), {"script": payload.script_id, "project": project_id, "workspace": workspace_id})).scalar_one_or_none()
    if not script_exists:
        raise HTTPException(status_code=409, detail="Storyboard requires an approved script in this project")
    indices = [scene.scene_index for scene in payload.scenes]
    if len(indices) != len(set(indices)):
        raise HTTPException(status_code=422, detail="Scene indices must be unique")
    version = (await db.execute(
        text("select coalesce(max(version),0)+1 from public.storyboards where project_id=:project"),
        {"project": project_id},
    )).scalar_one()
    row = (await db.execute(text("""
        insert into public.storyboards(
            workspace_id,project_id,script_id,version,global_visual_direction,created_by
        ) values (:workspace,:project,:script,:version,cast(:direction as jsonb),:actor)
        returning *
    """), {
        "workspace": workspace_id, "project": project_id, "script": payload.script_id,
        "version": version, "direction": json.dumps(payload.global_visual_direction, ensure_ascii=False),
        "actor": actor,
    })).mappings().one()
    for scene in payload.scenes:
        await db.execute(text("""
            insert into public.storyboard_scenes(
                workspace_id,project_id,storyboard_id,scene_index,title,purpose,narration_text,
                duration_ms,visual_direction,transition_in,transition_out,motion_plan,asset_requirements
            ) values (:workspace,:project,:storyboard,:idx,:title,:purpose,:narration,
                :duration,cast(:visual as jsonb),:transition_in,:transition_out,
                cast(:motion as jsonb),cast(:assets as jsonb))
        """), {
            "workspace": workspace_id, "project": project_id, "storyboard": row["id"],
            "idx": scene.scene_index, "title": scene.title, "purpose": scene.purpose,
            "narration": scene.narration_text, "duration": scene.duration_ms,
            "visual": json.dumps(scene.visual_direction, ensure_ascii=False),
            "transition_in": scene.transition_in, "transition_out": scene.transition_out,
            "motion": json.dumps(scene.motion_plan, ensure_ascii=False),
            "assets": json.dumps(scene.asset_requirements, ensure_ascii=False),
        })
    snapshot = _json_safe({"storyboard": dict(row), "scenes": [scene.model_dump() for scene in payload.scenes]})
    await _record_version(db, workspace_id=workspace_id, project_id=project_id,
        artifact_type="storyboard", artifact_id=row["id"], version=version,
        actor=actor, snapshot=snapshot, summary="Storyboard created")
    await _audit(db, request, actor, workspace_id, "storyboard.created", "storyboard", row["id"])
    await db.commit()
    return {"data": snapshot}


@router.patch("/projects/{project_id}/scenes/{scene_id}")
async def update_scene(
    project_id: UUID, scene_id: UUID, payload: SceneUpdate, request: Request,
    claims: AuthenticatedClaims, db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    workspace_id = await _project_scope(db, project_id, actor, "project.update")
    current = (await db.execute(text("""
        select s.* from public.storyboard_scenes s
        where s.id=:scene and s.project_id=:project and s.workspace_id=:workspace
    """), {"scene": scene_id, "project": project_id, "workspace": workspace_id})).mappings().first()
    if current is None:
        raise HTTPException(status_code=404, detail="Storyboard scene not found")
    merged = dict(current)
    merged.update(payload.model_dump(exclude_unset=True))
    row = (await db.execute(text("""
        update public.storyboard_scenes set title=:title,purpose=:purpose,
            narration_text=:narration,duration_ms=:duration,
            visual_direction=cast(:visual as jsonb),transition_in=:transition_in,
            transition_out=:transition_out,motion_plan=cast(:motion as jsonb),
            asset_requirements=cast(:assets as jsonb)
        where id=:scene and project_id=:project and workspace_id=:workspace returning *
    """), {
        "title": merged["title"], "purpose": merged["purpose"],
        "narration": merged["narration_text"], "duration": merged["duration_ms"],
        "visual": json.dumps(merged["visual_direction"], ensure_ascii=False),
        "transition_in": merged["transition_in"], "transition_out": merged["transition_out"],
        "motion": json.dumps(merged["motion_plan"], ensure_ascii=False),
        "assets": json.dumps(merged["asset_requirements"], ensure_ascii=False),
        "scene": scene_id, "project": project_id, "workspace": workspace_id,
    })).mappings().one()
    version = (await db.execute(text("""
        select coalesce(max(version),0)+1 from public.artifact_versions
        where project_id=:project and artifact_type='storyboard_scene' and artifact_id=:scene
    """), {"project": project_id, "scene": scene_id})).scalar_one()
    snapshot = {k: str(v) if isinstance(v, UUID) else v for k,v in dict(row).items()}
    await _record_version(db, workspace_id=workspace_id, project_id=project_id,
        artifact_type="storyboard_scene", artifact_id=scene_id, version=version,
        actor=actor, snapshot=snapshot, summary="Storyboard scene revised")
    await _audit(db, request, actor, workspace_id, "storyboard_scene.updated", "storyboard_scene", scene_id)
    await db.commit()
    return {"data": dict(row), "version": version}


@router.get("/projects/{project_id}/artifacts/versions")
async def list_artifact_versions(
    project_id: UUID, claims: AuthenticatedClaims, db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _project_scope(db, project_id, actor, "project.read")
    rows = (await db.execute(text("""
        select id,artifact_type,artifact_id,version,content_hash,created_by,
               created_by_agent,change_summary,created_at
        from public.artifact_versions where project_id=:project
        order by created_at desc
    """), {"project": project_id})).mappings().all()
    return {"data": [dict(row) for row in rows]}


class CreativeRunRequest(BaseModel):
    input_prompt: str | None = Field(default=None, min_length=1, max_length=20000)
    brief_id: UUID | None = None
    script_id: UUID | None = None
    source_material: list[dict[str, Any]] = Field(default_factory=list)
    approved_component_candidates: list[str] = Field(default_factory=list, max_length=100)


@router.post("/projects/{project_id}/creative-runs/{stage}", status_code=202)
async def execute_creative_stage(
    project_id: UUID,
    stage: Literal["brief", "script", "storyboard"],
    payload: CreativeRunRequest,
    request: Request,
    claims: AuthenticatedClaims,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    workspace_id = await _project_scope(db, project_id, actor, "project.update")
    if not idempotency_key or not 16 <= len(idempotency_key) <= 128:
        raise HTTPException(status_code=400, detail="Idempotency-Key header must contain 16-128 characters")

    stage_status = {"brief": "planning", "script": "scripting", "storyboard": "storyboarding"}[stage]
    input_snapshot = {
        "stage": stage, "input_prompt": payload.input_prompt, "brief_id": str(payload.brief_id) if payload.brief_id else None,
        "script_id": str(payload.script_id) if payload.script_id else None,
        "source_material": payload.source_material,
        "approved_component_candidates": payload.approved_component_candidates,
    }
    run = (await db.execute(text("""
        insert into public.production_runs(
            project_id,workspace_id,requested_by,status,current_stage,input_snapshot,
            config_snapshot,idempotency_key
        ) values (:project,:workspace,:actor,:status,:stage,cast(:input as jsonb),'{}'::jsonb,:key)
        on conflict (workspace_id,idempotency_key) do nothing returning *
    """), {
        "project": project_id, "workspace": workspace_id, "actor": actor,
        "stage": stage, "status": stage_status, "input": json.dumps(input_snapshot, ensure_ascii=False),
        "key": idempotency_key,
    })).mappings().first()
    if run is None:
        existing = (await db.execute(text("""
            select id,status,input_snapshot from public.production_runs
            where workspace_id=:workspace and idempotency_key=:key
        """), {"workspace": workspace_id, "key": idempotency_key})).mappings().first()
        if existing and existing["input_snapshot"] == input_snapshot:
            return {"data": {"run_id": str(existing["id"]), "status": existing["status"], "replayed": True}}
        raise HTTPException(status_code=409, detail="Idempotency-Key was already used for a different creative request")

    task = (await db.execute(text("""
        insert into public.agent_tasks(
            production_run_id,agent_key,task_type,status,input_payload,max_attempts
        ) values (:run,:agent,:task,'running',cast(:input as jsonb),2) returning id
    """), {
        "run": run["id"], "agent": {"brief":"prompt_interpreter","script":"scriptwriter","storyboard":"story_director+storyboard_director"}[stage],
        "task": stage, "input": json.dumps(input_snapshot, ensure_ascii=False),
    })).scalar_one()
    await db.execute(text("""
        insert into public.workflow_events(production_run_id,event_type,event_payload,sequence_number)
        values (:run,'stage.started',cast(:payload as jsonb),1)
    """), {"run": run["id"], "payload": json.dumps({"stage": stage})})
    await db.commit()

    try:
        if stage == "brief":
            if not payload.input_prompt:
                raise HTTPException(status_code=422, detail="input_prompt is required for brief generation")
            project = (await db.execute(text("""
                select p.default_language,p.production_mode,p.target_duration_ms,p.aspect_ratio,
                       p.width,p.height,p.fps,coalesce(ps.settings,'{}'::jsonb) as settings
                from public.video_projects p left join public.project_settings ps on ps.project_id=p.id
                where p.id=:project and p.workspace_id=:workspace
            """), {"project": project_id, "workspace": workspace_id})).mappings().first()
            if project is None:
                raise HTTPException(status_code=404, detail="Project not found")
            output, provenance = await creative_pipeline.interpret_prompt(
                input_prompt=payload.input_prompt,
                project_settings=dict(project),
                source_material=payload.source_material,
                idempotency_key=str(run["id"]),
            )
            version = (await db.execute(text(
                "select coalesce(max(version),0)+1 from public.creative_briefs where project_id=:project"
            ), {"project": project_id})).scalar_one()
            artifact = (await db.execute(text("""
                insert into public.creative_briefs(
                    workspace_id,project_id,version,input_prompt,normalized_brief,
                    source_references,created_by
                ) values (:workspace,:project,:version,:prompt,cast(:brief as jsonb),
                          cast(:sources as jsonb),:actor) returning *
            """), {
                "workspace": workspace_id, "project": project_id, "version": version,
                "prompt": payload.input_prompt.strip(),
                "brief": json.dumps(output.model_dump(), ensure_ascii=False),
                "sources": json.dumps(payload.source_material, ensure_ascii=False), "actor": actor,
            })).mappings().one()
            artifact_type = "creative_brief"
            artifact_id = artifact["id"]
            artifact_snapshot = dict(artifact)

        elif stage == "script":
            if not payload.brief_id:
                raise HTTPException(status_code=422, detail="brief_id is required for script generation")
            brief = (await db.execute(text("""
                select * from public.creative_briefs
                where id=:brief and project_id=:project and workspace_id=:workspace and status='approved'
            """), {"brief": payload.brief_id, "project": project_id, "workspace": workspace_id})).mappings().first()
            if brief is None:
                raise HTTPException(status_code=409, detail="Script generation requires an approved brief")
            output, provenance = await creative_pipeline.write_script(
                approved_brief=dict(brief["normalized_brief"]),
                source_material=payload.source_material,
                idempotency_key=str(run["id"]),
            )
            version = (await db.execute(text(
                "select coalesce(max(version),0)+1 from public.video_scripts where project_id=:project"
            ), {"project": project_id})).scalar_one()
            artifact = (await db.execute(text("""
                insert into public.video_scripts(
                    workspace_id,project_id,brief_id,version,language,title,hook,body,cta,
                    estimated_duration_ms,word_count,created_by_agent,created_by
                ) values (:workspace,:project,:brief,:version,:language,:title,:hook,
                    cast(:body as jsonb),:cta,:duration,:words,'scriptwriter',:actor) returning *
            """), {
                "workspace": workspace_id, "project": project_id, "brief": payload.brief_id,
                "version": version, "language": brief["normalized_brief"].get("language", "id-ID"),
                "title": output.title, "hook": output.hook,
                "body": json.dumps({"narration_segments":[x.model_dump() for x in output.narration_segments]}, ensure_ascii=False),
                "cta": output.cta, "duration": output.estimated_duration_ms,
                "words": output.word_count, "actor": actor,
            })).mappings().one()
            artifact_type = "video_script"
            artifact_id = artifact["id"]
            artifact_snapshot = dict(artifact)

        else:
            if not payload.script_id:
                raise HTTPException(status_code=422, detail="script_id is required for storyboard generation")
            script = (await db.execute(text("""
                select s.*,b.normalized_brief from public.video_scripts s
                left join public.creative_briefs b on b.id=s.brief_id
                where s.id=:script and s.project_id=:project and s.workspace_id=:workspace and s.status='approved'
            """), {"script": payload.script_id, "project": project_id, "workspace": workspace_id})).mappings().first()
            if script is None:
                raise HTTPException(status_code=409, detail="Storyboard generation requires an approved script")
            brief_payload = dict(script["normalized_brief"] or {})
            script_payload = {
                "title": script["title"], "hook": script["hook"], "body": dict(script["body"]),
                "cta": script["cta"], "language": script["language"],
                "estimated_duration_ms": script["estimated_duration_ms"],
            }
            arc, arc_meta = await creative_pipeline.direct_story(
                approved_brief=brief_payload, approved_script=script_payload,
                idempotency_key=f"{run['id']}:story-arc",
            )
            output, provenance = await creative_pipeline.direct_storyboard(
                approved_brief=brief_payload, approved_script=script_payload,
                story_arc=arc.model_dump(),
                approved_component_candidates=payload.approved_component_candidates,
                idempotency_key=f"{run['id']}:storyboard",
            )
            version = (await db.execute(text(
                "select coalesce(max(version),0)+1 from public.storyboards where project_id=:project"
            ), {"project": project_id})).scalar_one()
            global_direction = {**output.global_visual_direction, "story_arc": arc.model_dump()}
            artifact = (await db.execute(text("""
                insert into public.storyboards(
                    workspace_id,project_id,script_id,version,global_visual_direction,created_by
                ) values (:workspace,:project,:script,:version,cast(:direction as jsonb),:actor) returning *
            """), {
                "workspace": workspace_id, "project": project_id, "script": payload.script_id,
                "version": version, "direction": json.dumps(global_direction, ensure_ascii=False),
                "actor": actor,
            })).mappings().one()
            scene_snapshots = []
            for scene in output.scenes:
                scene_row = (await db.execute(text("""
                    insert into public.storyboard_scenes(
                        workspace_id,project_id,storyboard_id,scene_index,title,purpose,
                        narration_text,duration_ms,visual_direction,motion_plan,asset_requirements,
                        transition_in
                    ) values (:workspace,:project,:storyboard,:idx,:title,:purpose,:narration,
                        :duration,cast(:visual as jsonb),cast(:motion as jsonb),cast(:assets as jsonb),:transition)
                    returning *
                """), {
                    "workspace": workspace_id, "project": project_id, "storyboard": artifact["id"],
                    "idx": scene.scene_index, "title": scene.title, "purpose": scene.purpose,
                    "narration": None, "duration": scene.duration_ms,
                    "visual": json.dumps({
                        "description": scene.visual_description, "layout": scene.layout,
                        "camera_angle": scene.camera_angle, "shot_type": scene.shot_type,
                        "composition": scene.composition, "movement": scene.movement,
                        "lighting": scene.lighting, "on_screen_text": scene.on_screen_text,
                        "narration_segment_ids": scene.narration_segment_ids,
                    }, ensure_ascii=False),
                    "motion": json.dumps({"transition": scene.transition, "component_candidates": scene.component_candidates}, ensure_ascii=False),
                    "assets": json.dumps(scene.asset_requirements, ensure_ascii=False),
                    "transition": scene.transition,
                })).mappings().one()
                scene_snapshots.append(dict(scene_row))
            artifact_type = "storyboard"
            artifact_id = artifact["id"]
            artifact_snapshot = {"storyboard": dict(artifact), "scenes": scene_snapshots}
            provenance = {"story_director": arc_meta, "storyboard_director": provenance}

        safe_snapshot = _json_safe(artifact_snapshot)
        await _record_version(db, workspace_id=workspace_id, project_id=project_id,
            artifact_type=artifact_type, artifact_id=artifact_id, version=version,
            actor=actor, snapshot=safe_snapshot, summary=f"{stage.title()} generated by creative pipeline")
        await db.execute(text("""
            update public.agent_tasks set status='succeeded',output_artifact_id=:artifact,
                output_payload=cast(:output as jsonb),attempt_count=1,completed_at=now()
            where id=:task
        """), {
            "artifact": artifact_id, "output": json.dumps({"provenance": provenance, "artifact_id": str(artifact_id)}),
            "task": task,
        })
        await db.execute(text("""
            update public.production_runs set status='ready_for_review',current_stage=:stage,
                progress_percent=100,completed_at=now()
            where id=:run
        """), {"stage": stage, "run": run["id"]})
        await db.execute(text("""
            insert into public.workflow_checkpoints(production_run_id,stage_key,checkpoint_key,payload,content_hash)
            values (:run,:stage,:key,cast(:payload as jsonb),:hash)
            on conflict (production_run_id,checkpoint_key) do nothing
        """), {
            "run": run["id"], "stage": stage, "key": f"{stage}:completed",
            "payload": json.dumps({"artifact_type": artifact_type, "artifact_id": str(artifact_id)}),
            "hash": _snapshot_hash(safe_snapshot),
        })
        await db.execute(text("""
            insert into public.workflow_events(production_run_id,event_type,event_payload,sequence_number)
            values (:run,'stage.completed',cast(:payload as jsonb),2)
        """), {"run": run["id"], "payload": json.dumps({"stage": stage, "artifact_id": str(artifact_id)})})
        await _audit(db, request, actor, workspace_id, f"creative.{stage}.generated", artifact_type, artifact_id)
        await db.commit()
        return {"data": {"run_id": str(run["id"]), "status": "ready_for_review",
                         "artifact_type": artifact_type, "artifact": _json_safe(dict(artifact)),
                         "provenance": provenance}}
    except Exception as exc:
        await db.rollback()
        safe_code = exc.detail.get("code", "CREATIVE_STAGE_FAILED") if isinstance(exc, HTTPException) and isinstance(exc.detail, dict) else "CREATIVE_STAGE_FAILED"
        safe_message = exc.detail.get("message", "Creative stage could not be completed") if isinstance(exc, HTTPException) and isinstance(exc.detail, dict) else (
            exc.detail if isinstance(exc, HTTPException) and isinstance(exc.detail, str) else "Creative stage could not be completed"
        )
        await db.execute(text("""
            update public.agent_tasks set status='failed',error_code=:code,
                error_detail_internal=:detail,attempt_count=1,completed_at=now()
            where id=:task
        """), {"code": safe_code, "detail": str(exc)[:1000], "task": task})
        await db.execute(text("""
            update public.production_runs set status='failed',error_code=:code,
                error_message_safe=:message,completed_at=now()
            where id=:run
        """), {"code": safe_code, "message": str(safe_message)[:500], "run": run["id"]})
        await db.execute(text("""
            insert into public.workflow_events(production_run_id,event_type,event_payload,sequence_number)
            values (:run,'stage.failed',cast(:payload as jsonb),2)
        """), {"run": run["id"], "payload": json.dumps({"stage": stage, "error_code": safe_code})})
        await db.commit()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=500, detail="Creative stage failed") from exc
