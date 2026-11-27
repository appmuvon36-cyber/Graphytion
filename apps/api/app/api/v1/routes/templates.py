from __future__ import annotations

import copy
import json
import re
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthenticatedClaims, DbSession
from app.core.database import set_rls_subject
from app.services.composition_validation import validate_snapshot
from app.services.brand_kit import apply_brand_tokens
from app.services.workspace_authorization import WorkspacePermissionResolver

router = APIRouter()
permissions = WorkspacePermissionResolver()
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def actor_id(claims: dict[str, Any]) -> UUID:
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(401, "Invalid authenticated subject") from exc


async def project_scope(db: AsyncSession, project_id: UUID, actor: UUID, permission: str) -> UUID:
    workspace = await db.scalar(text("""
        select workspace_id from public.video_projects
        where id=:project and status <> 'deleted'
    """), {"project": project_id})
    if workspace is None:
        raise HTTPException(404, "Project not found")
    await permissions.require_permission(
        session=db, user_id=str(actor), workspace_id=str(workspace), permission=permission
    )
    await set_rls_subject(db, str(actor))
    return workspace


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    category: str = Field(min_length=1, max_length=48)
    tags: list[str] = Field(default_factory=list, max_length=20)


class BrandLogoLayout(BaseModel):
    width_percent: float = Field(default=16, ge=4, le=40)
    height_percent: float = Field(default=12, ge=4, le=40)
    opacity: float = Field(default=1, ge=0.1, le=1)
    anchor: Literal["top-left", "top-right", "bottom-left", "bottom-right", "center"] = "top-right"
    margin_percent: float = Field(default=4, ge=0, le=12)
    fit: Literal["contain", "cover"] = "contain"


class BrandConfig(BaseModel):
    colors: dict[str, str] = Field(default_factory=dict)
    typography: dict[str, str] = Field(default_factory=dict)
    logo_asset_id: UUID | None = None
    logo_layout: BrandLogoLayout = Field(default_factory=BrandLogoLayout)
    voice_style: str | None = Field(default=None, max_length=240)

    @field_validator("colors")
    @classmethod
    def valid_colors(cls, value: dict[str, str]) -> dict[str, str]:
        allowed = {"primary", "secondary", "accent", "background", "text", "muted", "surface"}
        if set(value) - allowed or any(not HEX.fullmatch(v) for v in value.values()):
            raise ValueError("Brand colors must use supported keys and #RRGGBB values")
        return value

    @field_validator("typography")
    @classmethod
    def valid_typography(cls, value: dict[str, str]) -> dict[str, str]:
        allowed = {"font_family", "heading_font_family", "body_font_family", "font_weight"}
        if set(value) - allowed or any(not v.strip() or len(v) > 120 for v in value.values()):
            raise ValueError("Unsupported or invalid typography token")
        return value


class BrandKitCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    config: BrandConfig


class BrandKitUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    config: BrandConfig | None = None
    status: str | None = Field(default=None, pattern="^(active|archived)$")


async def validate_logo_asset(db: AsyncSession, workspace_id: UUID, config: dict[str, Any]) -> None:
    asset_id = config.get("logo_asset_id")
    if not asset_id:
        return
    asset = (await db.execute(text("""
        select id,content_type from public.project_assets
        where id=:asset and workspace_id=:workspace and status='active'
    """), {"asset": asset_id, "workspace": workspace_id})).mappings().first()
    if asset is None:
        raise HTTPException(422, "Logo asset must be an active asset owned by this workspace")
    if asset["content_type"] not in {"image/png", "image/jpeg", "image/webp", "image/svg+xml"}:
        raise HTTPException(422, "Brand Kit logo must be a supported image asset")


def slugify(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not result:
        raise HTTPException(422, "Name must contain letters or numbers")
    return result[:80]


def reusable_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(snapshot)
    # A reusable template carries composition structure, not another project's
    # private media IDs. Media-bound clips are excluded until the user replaces
    # them with assets owned by the destination project.
    result["clips"] = [
        clip for clip in result.get("clips", [])
        if clip.get("componentKey") not in {"visual.image.v1", "visual.video.v1", "audio.clip.v1"}
        and not clip.get("assetId")
    ]
    result["assetRefs"] = []
    for clip in result["clips"]:
        clip.get("props", {}).pop("fontAssetId", None)
    result.pop("contentHash", None)
    result["durationFrames"] = max(
        1, max((clip["startFrame"] + clip["durationFrames"] for clip in result["clips"]), default=1)
    )
    return result


@router.get("/projects/{project_id}/templates")
async def list_templates(project_id: UUID, claims: AuthenticatedClaims, db: AsyncSession = DbSession):
    actor = actor_id(claims)
    workspace = await project_scope(db, project_id, actor, "project.read")
    rows = (await db.execute(text("""
        select distinct on (slug) id,slug,version,name,description,category,tags,aspect_ratios,status,created_at,updated_at
        from public.composition_templates
        where workspace_id=:workspace and status='published'
        order by slug,version desc
    """), {"workspace": workspace})).mappings().all()
    return {"data": [dict(row) for row in rows]}


@router.post("/projects/{project_id}/templates", status_code=201)
async def create_template(project_id: UUID, payload: TemplateCreate, claims: AuthenticatedClaims, db: AsyncSession = DbSession):
    actor = actor_id(claims)
    workspace = await project_scope(db, project_id, actor, "project.update")
    current = (await db.execute(text("""
        select snapshot from public.video_timelines
        where project_id=:project and workspace_id=:workspace
        order by version desc limit 1
    """), {"project": project_id, "workspace": workspace})).mappings().first()
    if current is None:
        raise HTTPException(409, "Save a valid timeline before creating a reusable template")
    snapshot = reusable_snapshot(dict(current["snapshot"]))
    validate_snapshot(snapshot)
    slug = slugify(payload.name)
    version = await db.scalar(text("""
        select coalesce(max(version),0)+1 from public.composition_templates
        where workspace_id=:workspace and slug=:slug
    """), {"workspace": workspace, "slug": slug})
    row = (await db.execute(text("""
        insert into public.composition_templates(
            workspace_id,slug,version,name,description,category,tags,aspect_ratios,
            composition_snapshot,created_by
        ) values (:workspace,:slug,:version,:name,:description,:category,:tags,
                  cast(:ratios as text[]),cast(:snapshot as jsonb),:actor)
        returning id,slug,version,name,description,category,tags,aspect_ratios,status,created_at
    """), {
        "workspace": workspace, "slug": slug, "version": version, "name": payload.name.strip(),
        "description": payload.description, "category": payload.category.strip().lower(),
        "tags": [tag.strip().lower()[:32] for tag in payload.tags if tag.strip()],
        "ratios": ["16:9", "9:16", "1:1", "4:5", "4:3"],
        "snapshot": json.dumps(snapshot), "actor": actor,
    })).mappings().one()
    await db.execute(text("""
        insert into public.audit_logs(actor_user_id,workspace_id,action,resource_type,resource_id)
        values (:actor,:workspace,'composition_template.created','composition_template',:id)
    """), {"actor": actor, "workspace": workspace, "id": row["id"]})
    await db.commit()
    return {"data": dict(row)}


@router.post("/projects/{project_id}/templates/{template_id}/apply")
async def apply_template(project_id: UUID, template_id: UUID, claims: AuthenticatedClaims, db: AsyncSession = DbSession):
    actor = actor_id(claims)
    workspace = await project_scope(db, project_id, actor, "project.update")
    template = (await db.execute(text("""
        select composition_snapshot from public.composition_templates
        where id=:id and workspace_id=:workspace and status='published'
    """), {"id": template_id, "workspace": workspace})).mappings().first()
    if template is None:
        raise HTTPException(404, "Published template not found in this workspace")
    project = (await db.execute(text("""
        select width,height,fps from public.video_projects
        where id=:project and workspace_id=:workspace
    """), {"project": project_id, "workspace": workspace})).mappings().one()
    brand_row=(await db.execute(text("""select bk.brand_config from public.video_projects p
        left join public.brand_kits bk on bk.id=p.brand_kit_id and bk.workspace_id=p.workspace_id
        where p.id=:project and p.workspace_id=:workspace"""),{"project":project_id,"workspace":workspace})).mappings().first()
    snapshot = copy.deepcopy(dict(template["composition_snapshot"]))
    snapshot["width"], snapshot["height"], snapshot["fps"] = project["width"], project["height"], project["fps"]
    snapshot["assetRefs"] = []
    snapshot = apply_brand_tokens(snapshot,dict(brand_row["brand_config"]) if brand_row and brand_row["brand_config"] else None)
    digest = validate_snapshot(snapshot)
    enabled_rows=(await db.execute(text("""select component_key,component_version from public.motion_component_controls
        where enabled=true and component_key=any(cast(:keys as text[]))"""),
        {"keys":list({clip["componentKey"] for clip in snapshot["clips"]})})).mappings().all()
    enabled={row["component_key"]:row["component_version"] for row in enabled_rows}
    if any(enabled.get(clip["componentKey"])!=clip["componentVersion"] for clip in snapshot["clips"]):
        raise HTTPException(422,"Template contains a disabled or unsupported motion component")
    await db.execute(text("select pg_advisory_xact_lock(hashtext(:project))"), {"project": str(project_id)})
    latest = await db.scalar(text("""
        select version from public.video_timelines where project_id=:project
        order by version desc limit 1 for update
    """), {"project": project_id})
    version = int(latest or 0) + 1
    row = (await db.execute(text("""
        insert into public.video_timelines(
            workspace_id,project_id,version,schema_version,fps,width,height,duration_frames,
            snapshot,compiled_hash,created_by
        ) values (:workspace,:project,:version,2,:fps,:width,:height,:duration,
                  cast(:snapshot as jsonb),:hash,:actor)
        returning id,version,created_at
    """), {
        "workspace": workspace, "project": project_id, "version": version,
        "fps": snapshot["fps"], "width": snapshot["width"], "height": snapshot["height"],
        "duration": snapshot["durationFrames"], "snapshot": json.dumps(snapshot),
        "hash": digest, "actor": actor,
    })).mappings().one()
    await db.execute(text("""
        insert into public.audit_logs(actor_user_id,workspace_id,action,resource_type,resource_id,metadata)
        values (:actor,:workspace,'composition_template.applied','video_timeline',:id,
                jsonb_build_object('template_id',:template,'version',:version))
    """), {"actor": actor, "workspace": workspace, "id": row["id"], "template": template_id, "version": version})
    await db.commit()
    return {"data": {"timeline_id": str(row["id"]), "version": version, "snapshot": snapshot, "compiled_hash": digest, "created_at": row["created_at"]}}


@router.get("/projects/{project_id}/brand-kits")
async def list_brand_kits(project_id: UUID, claims: AuthenticatedClaims, db: AsyncSession = DbSession):
    actor = actor_id(claims)
    workspace = await project_scope(db, project_id, actor, "project.read")
    rows = (await db.execute(text("""
        select distinct on (lower(name)) id,name,version,brand_config,status,created_at,updated_at
        from public.brand_kits where workspace_id=:workspace and status='active'
        order by lower(name),version desc
    """), {"workspace": workspace})).mappings().all()
    return {"data": [dict(row) for row in rows]}


@router.post("/projects/{project_id}/brand-kits", status_code=201)
async def create_brand_kit(project_id: UUID, payload: BrandKitCreate, claims: AuthenticatedClaims, db: AsyncSession = DbSession):
    actor = actor_id(claims)
    workspace = await project_scope(db, project_id, actor, "project.update")
    config = payload.config.model_dump(mode="json")
    await validate_logo_asset(db, workspace, config)
    version = await db.scalar(text("""
        select coalesce(max(version),0)+1 from public.brand_kits
        where workspace_id=:workspace and lower(name)=lower(:name)
    """), {"workspace": workspace, "name": payload.name.strip()})
    row = (await db.execute(text("""
        insert into public.brand_kits(workspace_id,name,version,brand_config,created_by)
        values (:workspace,:name,:version,cast(:config as jsonb),:actor)
        returning id,name,version,brand_config,status,created_at
    """), {"workspace": workspace, "name": payload.name.strip(), "version": version,
           "config": json.dumps(config), "actor": actor})).mappings().one()
    await db.execute(text("""
        insert into public.audit_logs(actor_user_id,workspace_id,action,resource_type,resource_id)
        values (:actor,:workspace,'brand_kit.created','brand_kit',:id)
    """), {"actor": actor, "workspace": workspace, "id": row["id"]})
    await db.commit()
    return {"data": dict(row)}


@router.patch("/projects/{project_id}/brand-kits/{brand_kit_id}")
async def update_brand_kit(project_id: UUID, brand_kit_id: UUID, payload: BrandKitUpdate, claims: AuthenticatedClaims, db: AsyncSession = DbSession):
    actor = actor_id(claims)
    workspace = await project_scope(db, project_id, actor, "project.update")
    current = (await db.execute(text("""
        select * from public.brand_kits where id=:id and workspace_id=:workspace
        order by version desc limit 1 for update
    """), {"id": brand_kit_id, "workspace": workspace})).mappings().first()
    if current is None:
        raise HTTPException(404, "Brand Kit not found")
    changes = payload.model_dump(exclude_unset=True)
    name = (changes.get("name") or current["name"]).strip()
    config = changes.get("config")
    brand_config = config.model_dump(mode="json") if config else dict(current["brand_config"])
    await validate_logo_asset(db, workspace, brand_config)
    next_status = changes.get("status") or current["status"]
    row = (await db.execute(text("""
        insert into public.brand_kits(workspace_id,name,version,brand_config,status,created_by)
        values (:workspace,:name,:version,cast(:config as jsonb),:status,:actor)
        returning id,name,version,brand_config,status,updated_at
    """), {"workspace": workspace, "name": name, "version": int(current["version"])+1,
           "config": json.dumps(brand_config), "status": next_status, "actor": actor})).mappings().one()
    await db.execute(text("update public.brand_kits set status='archived' where id=:id and workspace_id=:workspace"),
                     {"id": brand_kit_id, "workspace": workspace})
    if next_status == "active":
        await db.execute(text("""
            update public.video_projects set brand_kit_id=:new
            where workspace_id=:workspace and brand_kit_id=:old
        """), {"new": row["id"], "workspace": workspace, "old": brand_kit_id})
        await db.execute(text("""
            update public.project_settings ps set
              settings=coalesce(ps.settings,'{}'::jsonb)||jsonb_build_object('brand_kit',cast(:snapshot as jsonb)),
              version=ps.version+1,updated_at=now()
            from public.video_projects p
            where p.id=ps.project_id and p.workspace_id=:workspace and p.brand_kit_id=:new
        """), {"snapshot": json.dumps({**brand_config,"id":str(row["id"]),"name":row["name"],"version":row["version"]}),
               "workspace": workspace, "new": row["id"]})
    await db.execute(text("""
        insert into public.audit_logs(actor_user_id,workspace_id,action,resource_type,resource_id,metadata)
        values (:actor,:workspace,'brand_kit.versioned','brand_kit',:id,
                jsonb_build_object('previous_version_id',:previous,'version',:version))
    """), {"actor": actor, "workspace": workspace, "id": row["id"],
           "previous": brand_kit_id, "version": row["version"]})
    await db.commit()
    return {"data": dict(row)}


@router.put("/projects/{project_id}/brand-kits/{brand_kit_id}/apply")
async def apply_brand_kit(project_id: UUID, brand_kit_id: UUID, claims: AuthenticatedClaims, db: AsyncSession = DbSession):
    actor = actor_id(claims)
    workspace = await project_scope(db, project_id, actor, "project.update")
    kit = (await db.execute(text("""
        select id,name,version,brand_config from public.brand_kits
        where id=:id and workspace_id=:workspace and status='active'
        order by version desc limit 1
    """), {"id": brand_kit_id, "workspace": workspace})).mappings().first()
    if kit is None:
        raise HTTPException(404, "Active Brand Kit not found")
    config = dict(kit["brand_config"])
    await validate_logo_asset(db, workspace, config)
    await db.execute(text("""
        update public.video_projects set brand_kit_id=:kit
        where id=:project and workspace_id=:workspace
    """), {"kit": brand_kit_id, "project": project_id, "workspace": workspace})
    await db.execute(text("""
        insert into public.project_settings(project_id,settings,version)
        values (:project,jsonb_build_object('brand_kit',cast(:config as jsonb)),1)
        on conflict(project_id) do update set
          settings=coalesce(public.project_settings.settings,'{}'::jsonb)
            || jsonb_build_object('brand_kit',cast(:config as jsonb)),
          version=public.project_settings.version+1,updated_at=now()
    """), {"project": project_id, "config": json.dumps({**config,"id":str(kit["id"]),"name":kit["name"],"version":kit["version"]})})
    await db.execute(text("""
        insert into public.audit_logs(actor_user_id,workspace_id,action,resource_type,resource_id)
        values (:actor,:workspace,'brand_kit.applied','video_project',:project)
    """), {"actor": actor, "workspace": workspace, "project": project_id})
    await db.commit()
    return {"data": {"project_id": str(project_id), "brand_kit_id": str(brand_kit_id), "brand_config": config}}
