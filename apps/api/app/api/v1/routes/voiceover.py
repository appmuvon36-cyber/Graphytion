from __future__ import annotations
import hashlib,hmac,json
from typing import Any
from uuid import UUID,uuid4
from fastapi import APIRouter,Header,HTTPException,Query,Request,UploadFile
from pydantic import BaseModel,Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import AuthenticatedClaims,DbSession
from app.core.config import settings
from app.core.database import set_rls_subject
from app.core.redis import redis_client
from app.services.supabase_storage import SupabaseStorage
from app.services.workspace_authorization import WorkspacePermissionResolver
from app.services.tts_gateway import OpenAITTSProvider

router=APIRouter();permissions=WorkspacePermissionResolver()
STREAM="graphytion:media:tts";BUCKET="project-assets";MAX_AUDIO_BYTES=50*1024*1024
provider=OpenAITTSProvider(settings.openai_api_key_value or "")
class VoiceoverCreate(BaseModel):
 text:str=Field(min_length=1,max_length=20000)
 provider_key:str=Field(default="openai",pattern=r"^openai$")
 model_key:str=Field(default="tts-1",pattern=r"^(tts-1|tts-1-hd|gpt-4o-mini-tts)$")
 voice_key:str=Field(default="alloy",pattern=r"^(alloy|ash|coral|echo|fable|onyx|nova|sage|shimmer|verse)$")
 language:str=Field(default="id-ID",min_length=2,max_length=16)
 scene_id:UUID|None=None
 generation_config:dict[str,Any]=Field(default_factory=dict)
class VoiceoverFailure(BaseModel):
 error_code:str=Field(min_length=1,max_length=100)
 retryable:bool=False
def _actor(claims:dict[str,Any])->UUID:
 try:return UUID(str(claims["sub"]))
 except (KeyError,ValueError,TypeError) as exc:raise HTTPException(401,"Invalid authenticated subject") from exc
async def _scope(db:AsyncSession,project:UUID,actor:UUID,permission:str)->UUID:
 workspace=await db.scalar(text("select workspace_id from public.video_projects where id=:id and status<>'deleted'"),{"id":project})
 if not workspace:raise HTTPException(404,"Project not found")
 await permissions.require_permission(session=db,user_id=str(actor),workspace_id=str(workspace),permission=permission)
 await set_rls_subject(db,str(actor));return workspace
def _require_worker(request:Request)->None:
 configured=settings.internal_worker_token.get_secret_value() if settings.internal_worker_token else ""
 supplied=request.headers.get("Authorization","").removeprefix("Bearer ").strip()
 if not configured or not supplied or not hmac.compare_digest(configured,supplied):raise HTTPException(401,"Internal worker authentication required")
@router.post("/projects/{project_id}/voiceovers",status_code=202)
async def create_voiceover(project_id:UUID,payload:VoiceoverCreate,request:Request,claims:AuthenticatedClaims,idempotency_key:str|None=Header(default=None,alias="Idempotency-Key"),db:AsyncSession=DbSession):
 actor=_actor(claims);workspace=await _scope(db,project_id,actor,"project.update")
 if not idempotency_key or not 16<=len(idempotency_key)<=128:raise HTTPException(400,"Idempotency-Key must contain 16-128 characters")
 if payload.scene_id:
  exists=await db.scalar(text("select exists(select 1 from public.storyboard_scenes ss join public.storyboards sb on sb.id=ss.storyboard_id where ss.id=:scene and sb.project_id=:project)"),{"scene":payload.scene_id,"project":project_id})
  if not exists:raise HTTPException(404,"Scene does not belong to this project")
 status="queued" if provider.configured() else "provider_unavailable"
 row=(await db.execute(text("""insert into public.audio_generations(workspace_id,project_id,scene_id,requested_by,provider_key,model_key,voice_key,input_text,language,generation_config,status,idempotency_key)
 values(:workspace,:project,:scene,:actor,:provider,:model,:voice,:input,:language,cast(:config as jsonb),:status,:key)
 on conflict(workspace_id,idempotency_key) do nothing returning id,status"""),{"workspace":workspace,"project":project_id,"scene":payload.scene_id,"actor":actor,"provider":payload.provider_key,"model":payload.model_key,"voice":payload.voice_key,"input":payload.text,"language":payload.language,"config":json.dumps(payload.generation_config),"status":status,"key":idempotency_key})).mappings().first()
 if row is None:
  old=(await db.execute(text("select id,status,input_text,voice_key,model_key from public.audio_generations where workspace_id=:workspace and idempotency_key=:key"),{"workspace":workspace,"key":idempotency_key})).mappings().first()
  if not old or old["input_text"]!=payload.text or old["voice_key"]!=payload.voice_key or old["model_key"]!=payload.model_key:raise HTTPException(409,"Idempotency key was used for a different voiceover request")
  return {"data":{"voiceover_id":str(old["id"]),"status":old["status"],"replayed":True}}
 await db.execute(text("insert into public.audit_logs(actor_user_id,workspace_id,action,resource_type,resource_id,request_id,metadata) values(:actor,:workspace,'voiceover.requested','audio_generation',:id,:request,cast(:metadata as jsonb))"),{"actor":actor,"workspace":workspace,"id":row["id"],"request":request.state.request_id,"metadata":json.dumps({"provider":payload.provider_key,"model":payload.model_key,"voice":payload.voice_key,"status":status})})
 await db.commit()
 if status=="queued":
  try:await redis_client.xadd(STREAM,{"generation_id":str(row["id"])},maxlen=10000,approximate=True)
  except Exception:pass
 return {"data":{"voiceover_id":str(row["id"]),"status":status,"provider_configured":provider.configured()}}
@router.get("/projects/{project_id}/voiceovers")
async def list_voiceovers(project_id:UUID,claims:AuthenticatedClaims,db:AsyncSession=DbSession):
 actor=_actor(claims);await _scope(db,project_id,actor,"project.read")
 rows=(await db.execute(text("select id,scene_id,provider_key,model_key,voice_key,language,status,asset_id,error_code,attempt_count,created_at,completed_at from public.audio_generations where project_id=:project order by created_at desc"),{"project":project_id})).mappings().all()
 return {"data":[dict(r) for r in rows]}
@router.get("/voiceovers/{voiceover_id}")
async def get_voiceover(voiceover_id:UUID,claims:AuthenticatedClaims,db:AsyncSession=DbSession):
 actor=_actor(claims);row=(await db.execute(text("select * from public.audio_generations where id=:id"),{"id":voiceover_id})).mappings().first()
 if not row:raise HTTPException(404,"Voiceover job not found")
 await _scope(db,row["project_id"],actor,"project.read")
 return {"data":{k:row[k] for k in ("id","project_id","scene_id","provider_key","model_key","voice_key","language","status","asset_id","error_code","attempt_count","created_at","completed_at")}}
@router.post("/voiceovers/{voiceover_id}/retry",status_code=202)
async def retry_voiceover(voiceover_id:UUID,claims:AuthenticatedClaims,db:AsyncSession=DbSession):
 actor=_actor(claims)
 row=(await db.execute(text("select id,project_id,workspace_id,status from public.audio_generations where id=:id"),{"id":voiceover_id})).mappings().first()
 if not row:raise HTTPException(404,"Voiceover job not found")
 await _scope(db,row["project_id"],actor,"project.update")
 if not provider.configured():raise HTTPException(409,"TTS provider credentials are not configured")
 if row["status"] not in {"provider_unavailable","failed"}:raise HTTPException(409,"Only unavailable or failed voiceover jobs can be retried")
 await db.execute(text("update public.audio_generations set status='queued',error_code=null,attempt_count=0,worker_id=null,lease_expires_at=null where id=:id"),{"id":voiceover_id})
 await db.commit()
 try:await redis_client.xadd(STREAM,{"generation_id":str(voiceover_id)},maxlen=10000,approximate=True)
 except Exception:pass
 return {"data":{"voiceover_id":str(voiceover_id),"status":"queued"}}


@router.post("/internal/media-jobs/claim")
async def claim_media_job(request:Request,worker_id:str=Query(min_length=1,max_length=128),generation_id:UUID|None=Query(default=None),db:AsyncSession=DbSession):
 _require_worker(request)
 row=(await db.execute(text("select * from private.graphytion_claim_audio_generation(:worker,cast(:id as uuid))"),{"id":generation_id,"worker":worker_id})).mappings().first()
 if not row:await db.rollback();return {"data":None}
 await set_rls_subject(db,str(row["requested_by"]));await db.commit()
 return {"data":{"id":str(row["id"]),"project_id":str(row["project_id"]),"workspace_id":str(row["workspace_id"]),"requested_by":str(row["requested_by"]),"input_text":row["input_text"],"voice_key":row["voice_key"],"model_key":row["model_key"],"generation_config":row["generation_config"],"language":row["language"],"attempt_count":row["attempt_count"]}}
@router.post("/internal/media-jobs/{generation_id}/heartbeat")
async def heartbeat_media_job(generation_id:UUID,request:Request,worker_id:str=Query(min_length=1,max_length=128),db:AsyncSession=DbSession):
 _require_worker(request)
 owner=await db.scalar(text("select private.graphytion_heartbeat_media_job(:id,:worker)"),{"id":generation_id,"worker":worker_id})
 if not owner:raise HTTPException(409,"Media job lease is no longer owned")
 await set_rls_subject(db,str(owner));await db.commit();return {"data":{"generation_id":str(generation_id),"lease_extended":True}}
@router.post("/internal/media-jobs/{generation_id}/artifact",status_code=201)
async def complete_media_artifact(generation_id:UUID,request:Request,file:UploadFile,worker_id:str=Query(min_length=1,max_length=128),db:AsyncSession=DbSession):
 _require_worker(request)
 owner=await db.scalar(text("select private.graphytion_media_job_owner(:id,:worker)"),{"id":generation_id,"worker":worker_id})
 if not owner:raise HTTPException(409,"Media job lease is no longer owned")
 await set_rls_subject(db,str(owner))
 row=(await db.execute(text("select * from public.audio_generations where id=:id and worker_id=:worker and status='running'"),{"id":generation_id,"worker":worker_id})).mappings().first()
 if not row:raise HTTPException(409,"Media job lease is no longer owned")
 content=await file.read(MAX_AUDIO_BYTES+1)
 valid=file.content_type=="audio/mpeg" and (content.startswith(b"ID3") or (len(content)>1 and content[0]==0xFF and content[1]&0xE0==0xE0))
 if not valid or not 1<=len(content)<=MAX_AUDIO_BYTES:raise HTTPException(415,"Voiceover output must be a valid MP3 under 50 MB")
 asset_id=uuid4();digest=hashlib.sha256(content).hexdigest();path=f"{row['workspace_id']}/{row['project_id']}/{asset_id}.mp3"
 try:
  await SupabaseStorage().upload(bucket=BUCKET,object_path=path,content=content,content_type="audio/mpeg",upsert=False,timeout_seconds=180)
  await db.execute(text("insert into public.project_assets(id,workspace_id,project_id,uploaded_by,bucket,object_path,file_name,content_type,size_bytes,sha256) values(:id,:workspace,:project,:actor,:bucket,:path,:name,'audio/mpeg',:size,:hash)"),{"id":asset_id,"workspace":row["workspace_id"],"project":row["project_id"],"actor":row["requested_by"],"bucket":BUCKET,"path":path,"name":"voiceover-"+str(generation_id)+".mp3","size":len(content),"hash":digest})
  await db.execute(text("update public.audio_generations set status='completed',asset_id=:asset,completed_at=now(),worker_id=null,lease_expires_at=null where id=:id"),{"asset":asset_id,"id":generation_id})
  await db.commit()
 except Exception as exc:
  await db.rollback()
  try:await SupabaseStorage().remove(bucket=BUCKET,object_path=path)
  except Exception:pass
  raise HTTPException(502,"Voiceover artifact persistence failed") from exc
 return {"data":{"generation_id":str(generation_id),"asset_id":str(asset_id),"status":"completed","size_bytes":len(content),"sha256":digest}}
@router.post("/internal/media-jobs/{generation_id}/failed")
async def fail_media_job(generation_id:UUID,payload:VoiceoverFailure,request:Request,worker_id:str=Query(min_length=1,max_length=128),db:AsyncSession=DbSession):
 _require_worker(request)
 owner=await db.scalar(text("select private.graphytion_media_job_owner(:id,:worker)"),{"id":generation_id,"worker":worker_id})
 if not owner:raise HTTPException(409,"Media job lease is no longer owned")
 await set_rls_subject(db,str(owner))
 row=(await db.execute(text("select id,requested_by,attempt_count,max_attempts from public.audio_generations where id=:id and worker_id=:worker and status='running'"),{"id":generation_id,"worker":worker_id})).mappings().first()
 if not row:raise HTTPException(409,"Media job lease is no longer owned")
 retry=payload.retryable and row["attempt_count"]<row["max_attempts"]
 await db.execute(text("update public.audio_generations set status=:status,error_code=:code,worker_id=null,lease_expires_at=null where id=:id"),{"status":"queued" if retry else "failed","code":payload.error_code[:100],"id":generation_id})
 await db.commit()
 if retry:
  try:await redis_client.xadd(STREAM,{"generation_id":str(generation_id)},maxlen=10000,approximate=True)
  except Exception:pass
 return {"data":{"generation_id":str(generation_id),"status":"queued" if retry else "failed"}}
@router.post("/internal/media-jobs/recover")
async def recover_media_jobs(request:Request,db:AsyncSession=DbSession):
 _require_worker(request)
 rows=(await db.execute(text("select private.graphytion_recover_audio_generations()"))).scalars().all()
 await db.commit()
 for item in rows:
  try:await redis_client.xadd(STREAM,{"generation_id":str(item)},maxlen=10000,approximate=True)
  except Exception:pass
 return {"data":{"recovered_jobs":len(rows)}}
