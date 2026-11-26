from __future__ import annotations
import json
from typing import Any
from uuid import UUID
from fastapi import APIRouter,HTTPException,Request
from pydantic import BaseModel,Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import AuthenticatedClaims,DbSession
from app.core.database import set_rls_subject
from app.services.composition_validation import validate_snapshot
from app.services.composition_assets import collect_asset_ids,resolve_project_assets
from app.services.workspace_authorization import WorkspacePermissionResolver

router=APIRouter();permissions=WorkspacePermissionResolver()
class TimelineSave(BaseModel):
 snapshot:dict[str,Any]
 expected_version:int|None=Field(default=None,ge=1)
class _Actor:
 @staticmethod
 def get(claims:dict[str,Any])->UUID:
  try:return UUID(str(claims["sub"]))
  except (KeyError,ValueError,TypeError) as exc:raise HTTPException(401,"Invalid authenticated subject") from exc
async def _scope(db:AsyncSession,project:UUID,actor:UUID,permission:str)->UUID:
 workspace=await db.scalar(text("select workspace_id from public.video_projects where id=:id and status<>'deleted'"),{"id":project})
 if not workspace:raise HTTPException(404,"Project not found")
 await permissions.require_permission(session=db,user_id=str(actor),workspace_id=str(workspace),permission=permission)
 await set_rls_subject(db,str(actor))
 return workspace
async def _component_gate(db:AsyncSession,snapshot:dict[str,Any])->None:
 keys=list({c["componentKey"] for c in snapshot["clips"]})
 rows=(await db.execute(text("""select component_key,component_version from public.motion_component_controls where enabled=true and component_key=any(cast(:keys as text[]))"""),{"keys":keys})).mappings().all()
 enabled={r["component_key"]:r["component_version"] for r in rows}
 for clip in snapshot["clips"]:
  if enabled.get(clip["componentKey"])!=clip["componentVersion"]:raise HTTPException(422,f"Motion component {clip['componentKey']} is disabled or its schema version is not enabled")
@router.get("/projects/{project_id}/timeline")
async def get_latest_timeline(project_id:UUID,claims:AuthenticatedClaims,db:AsyncSession=DbSession):
 actor=_Actor.get(claims);workspace=await _scope(db,project_id,actor,"project.read")
 row=(await db.execute(text("""select id,version,schema_version,snapshot,compiled_hash,created_at from public.video_timelines where project_id=:project and workspace_id=:workspace order by version desc limit 1"""),{"project":project_id,"workspace":workspace})).mappings().first()
 if not row:raise HTTPException(404,"No saved timeline exists for this project")
 snapshot=dict(row["snapshot"]);assets=await resolve_project_assets(db,project_id=project_id,workspace_id=workspace,asset_ids=collect_asset_ids(snapshot),snapshot=snapshot)
 return {"data":{"timeline_id":str(row["id"]),"version":row["version"],"snapshot":snapshot,"resolved_assets":assets,"compiled_hash":row["compiled_hash"],"created_at":row["created_at"]}}
@router.put("/projects/{project_id}/timeline")
async def save_timeline(project_id:UUID,payload:TimelineSave,request:Request,claims:AuthenticatedClaims,db:AsyncSession=DbSession):
 actor=_Actor.get(claims);workspace=await _scope(db,project_id,actor,"project.update")
 snapshot=dict(payload.snapshot);snapshot.pop("contentHash",None);digest=validate_snapshot(snapshot);snapshot["contentHash"]=digest
 await _component_gate(db,snapshot)
 assets=collect_asset_ids(snapshot)
 resolved_assets=await resolve_project_assets(db,project_id=project_id,workspace_id=workspace,asset_ids=assets,expires_in=300,snapshot=snapshot)
 await db.execute(text("select pg_advisory_xact_lock(hashtext(:project))"),{"project":str(project_id)})
 latest=(await db.execute(text("select version from public.video_timelines where project_id=:project order by version desc limit 1 for update"),{"project":project_id})).scalar_one_or_none()
 current=int(latest or 0)
 if payload.expected_version is not None and payload.expected_version!=current:raise HTTPException(409,detail={"message":"Timeline changed since it was loaded","current_version":current})
 version=current+1
 row=(await db.execute(text("""insert into public.video_timelines(workspace_id,project_id,version,schema_version,fps,width,height,duration_frames,snapshot,compiled_hash,created_by)
 values(:workspace,:project,:version,2,:fps,:width,:height,:duration,cast(:snapshot as jsonb),:hash,:actor)
 returning id,version,created_at"""),{"workspace":workspace,"project":project_id,"version":version,"fps":snapshot["fps"],"width":snapshot["width"],"height":snapshot["height"],"duration":snapshot["durationFrames"],"snapshot":json.dumps(snapshot),"hash":digest,"actor":actor})).mappings().one()
 await db.execute(text("""insert into public.audit_logs(actor_user_id,workspace_id,action,resource_type,resource_id,request_id,metadata)
 values(:actor,:workspace,'timeline.version.saved','video_timeline',:id,:request,cast(:metadata as jsonb))"""),{"actor":actor,"workspace":workspace,"id":row["id"],"request":request.state.request_id,"metadata":json.dumps({"version":version,"hash":digest,"clips":len(snapshot["clips"]),"tracks":len(snapshot["tracks"])})})
 await db.commit()
 return {"data":{"timeline_id":str(row["id"]),"version":version,"compiled_hash":digest,"created_at":row["created_at"],"snapshot":snapshot,"resolved_assets":resolved_assets}}
@router.get("/projects/{project_id}/timelines")
async def list_timeline_versions(project_id:UUID,claims:AuthenticatedClaims,limit:int=50,db:AsyncSession=DbSession):
 actor=_Actor.get(claims);workspace=await _scope(db,project_id,actor,"project.read")
 if not 1<=limit<=100:raise HTTPException(422,"Timeline history limit must be between 1 and 100")
 rows=(await db.execute(text("""select id,version,schema_version,fps,width,height,duration_frames,compiled_hash,created_at
 from public.video_timelines where project_id=:project and workspace_id=:workspace order by version desc limit :limit"""),{"project":project_id,"workspace":workspace,"limit":limit})).mappings().all()
 return {"data":[dict(r) for r in rows]}


@router.get("/projects/{project_id}/timelines/{timeline_id}")
async def get_timeline_version(project_id:UUID,timeline_id:UUID,claims:AuthenticatedClaims,db:AsyncSession=DbSession):
 actor=_Actor.get(claims);workspace=await _scope(db,project_id,actor,"project.read")
 row=(await db.execute(text("""select id,version,snapshot,compiled_hash,created_at from public.video_timelines where id=:id and project_id=:project and workspace_id=:workspace"""),{"id":timeline_id,"project":project_id,"workspace":workspace})).mappings().first()
 if not row:raise HTTPException(404,"Timeline version not found")
 snapshot=dict(row["snapshot"]);assets=await resolve_project_assets(db,project_id=project_id,workspace_id=workspace,asset_ids=collect_asset_ids(snapshot))
 return {"data":{"timeline_id":str(row["id"]),"version":row["version"],"snapshot":snapshot,"resolved_assets":assets,"compiled_hash":row["compiled_hash"],"created_at":row["created_at"]}}
