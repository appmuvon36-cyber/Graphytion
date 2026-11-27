from __future__ import annotations
import hashlib,hmac,json
from typing import Any
from uuid import UUID,uuid4
from fastapi import APIRouter,File,Form,Header,HTTPException,Query,Request,UploadFile
from pydantic import BaseModel,Field,model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import AuthenticatedClaims,DbSession
from app.core.config import settings
from app.core.database import set_rls_subject
from app.services.supabase_storage import SupabaseStorage
from app.services.workspace_authorization import WorkspacePermissionResolver
from app.services.queue_notifications import notify_worker
from app.services.quota import reserve_fixed_operation, reconcile_fixed_operation, release_fixed_operation

router=APIRouter();permissions=WorkspacePermissionResolver()
BUCKET="project-assets";MAX_AUDIO_BYTES=50*1024*1024
class VoiceoverCreate(BaseModel):
 text:str=Field(min_length=1,max_length=20000)
 provider_key:str=Field(default="gemini",pattern=r"^(gemini|openai)$")
 model_key:str=Field(default="gemini-3.8-flash-lite-tts",pattern=r"^(gemini-[a-zA-Z0-9.-]+-tts|tts-1|tts-1-hd|gpt-4o-mini-tts)$",max_length=100)
 voice_key:str=Field(default="Kore",min_length=2,max_length=40)
 language:str=Field(default="id-ID",min_length=2,max_length=16)
 scene_id:UUID|None=None
 generation_config:dict[str,Any]=Field(default_factory=dict)
 subtitle_segment_id:UUID|None=None

 @model_validator(mode="after")
 def validate_provider_options(self):
  if self.provider_key=="gemini":
   voices={"Kore","Puck","Charon","Fenrir","Aoede","Leda","Orus","Zephyr","Callirrhoe","Autonoe","Enceladus","Iapetus","Umbriel","Algieba","Despina","Erinome","Algenib","Rasalgethi","Laomedeia","Achernar","Alnilam","Schedar","Gacrux","Pulcherrima","Achird","Zubenelgenubi","Vindemiatrix","Sadachbia","Sadaltager","Sulafat"}
   if not self.model_key.startswith("gemini-") or not self.model_key.endswith("-tts") or self.voice_key not in voices:
    raise ValueError("Gemini TTS requires a Gemini TTS model and a supported prebuilt voice")
  else:
   voices={"alloy","ash","coral","echo","fable","onyx","nova","sage","shimmer","verse"}
   if self.model_key not in {"tts-1","tts-1-hd","gpt-4o-mini-tts"} or self.voice_key not in voices:
    raise ValueError("OpenAI TTS requires a supported model and voice")
  return self

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
 if payload.subtitle_segment_id:
  exists=await db.scalar(text("select exists(select 1 from public.subtitle_segments s join public.subtitle_tracks t on t.id=s.track_id where s.id=:segment and t.project_id=:project and t.workspace_id=:workspace)"),{"segment":payload.subtitle_segment_id,"project":project_id,"workspace":workspace})
  if not exists:raise HTTPException(404,"Subtitle segment does not belong to this project")
 status="queued"
 row=(await db.execute(text("""insert into public.audio_generations(workspace_id,project_id,scene_id,subtitle_segment_id,requested_by,provider_key,model_key,voice_key,input_text,language,generation_config,status,idempotency_key)
 values(:workspace,:project,:scene,:segment,:actor,:provider,:model,:voice,:input,:language,cast(:config as jsonb),:status,:key)
 on conflict(workspace_id,idempotency_key) do nothing returning id,status"""),{"workspace":workspace,"project":project_id,"scene":payload.scene_id,"segment":payload.subtitle_segment_id,"actor":actor,"provider":payload.provider_key,"model":payload.model_key,"voice":payload.voice_key,"input":payload.text,"language":payload.language,"config":json.dumps(payload.generation_config),"status":status,"key":idempotency_key})).mappings().first()
 if row is not None:
  await reserve_fixed_operation(db,workspace_id=workspace,project_id=project_id,resource_type="voiceover",
   resource_id=row["id"],operation_key="voiceover_per_1000_chars",
   units=max(1,(len(payload.text)+999)//1000),idempotency_key="voiceover:"+str(row["id"])+":attempt:1")
 if row is None:
  old=(await db.execute(text("select id,status,input_text,provider_key,voice_key,model_key,subtitle_segment_id,language,scene_id,generation_config from public.audio_generations where workspace_id=:workspace and idempotency_key=:key"),{"workspace":workspace,"key":idempotency_key})).mappings().first()
  if (not old or old["input_text"]!=payload.text or old["provider_key"]!=payload.provider_key or old["voice_key"]!=payload.voice_key or old["model_key"]!=payload.model_key or old["subtitle_segment_id"]!=payload.subtitle_segment_id or old["language"]!=payload.language or old["scene_id"]!=payload.scene_id or old["generation_config"]!=(payload.generation_config or {})):raise HTTPException(409,"Idempotency key was used for a different voiceover request")
  return {"data":{"voiceover_id":str(old["id"]),"status":old["status"],"replayed":True}}
 await db.execute(text("insert into public.audit_logs(actor_user_id,workspace_id,action,resource_type,resource_id,request_id,metadata) values(:actor,:workspace,'voiceover.requested','audio_generation',:id,:request,cast(:metadata as jsonb))"),{"actor":actor,"workspace":workspace,"id":row["id"],"request":request.state.request_id,"metadata":json.dumps({"provider":payload.provider_key,"model":payload.model_key,"voice":payload.voice_key,"status":status})})
 await db.commit()
 await notify_worker("media", str(row["id"]))
 # PostgreSQL remains durable; Redis only wakes an idle media worker.
 return {"data":{"voiceover_id":str(row["id"]),"status":status}}
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
 analysis=(await db.execute(text("""select waveform_bucket,waveform_path,waveform_sha256,media_metadata,created_at
  from public.audio_analysis_artifacts where audio_generation_id=:id"""),{"id":voiceover_id})).mappings().first()
 waveform=None
 if analysis:
  waveform={**dict(analysis),"signed_url":await SupabaseStorage().create_signed_url(bucket=analysis["waveform_bucket"],object_path=analysis["waveform_path"],expires_in=300)}
 return {"data":{**{k:row[k] for k in ("id","project_id","scene_id","subtitle_segment_id","provider_key","model_key","voice_key","language","status","asset_id","error_code","attempt_count","created_at","completed_at","alignment_status","alignment_result")},"audio_analysis":waveform}}
@router.post("/voiceovers/{voiceover_id}/retry",status_code=202)
async def retry_voiceover(voiceover_id:UUID,claims:AuthenticatedClaims,db:AsyncSession=DbSession):
 actor=_actor(claims)
 row=(await db.execute(text("select id,project_id,workspace_id,status,input_text from public.audio_generations where id=:id"),{"id":voiceover_id})).mappings().first()
 if not row:raise HTTPException(404,"Voiceover job not found")
 await _scope(db,row["project_id"],actor,"project.update")
 if row["status"] not in {"provider_unavailable","failed"}:raise HTTPException(409,"Only unavailable or failed voiceover jobs can be retried")
 await db.execute(text("update public.audio_generations set status='queued',error_code=null,attempt_count=0,worker_id=null,lease_expires_at=null where id=:id"),{"id":voiceover_id})
 await reserve_fixed_operation(db,workspace_id=row["workspace_id"],project_id=row["project_id"],resource_type="voiceover",
  resource_id=voiceover_id,operation_key="voiceover_per_1000_chars",
  units=max(1,(len(row["input_text"])+999)//1000),idempotency_key="voiceover:"+str(voiceover_id)+":retry:"+str(uuid4()))
 await db.commit()
 await notify_worker("media", str(voiceover_id))
 # PostgreSQL remains durable; Redis is a best-effort wake-up signal.
 return {"data":{"voiceover_id":str(voiceover_id),"status":"queued"}}


@router.post("/voiceovers/{voiceover_id}/cancel")
async def cancel_voiceover(voiceover_id:UUID,request:Request,claims:AuthenticatedClaims,db:AsyncSession=DbSession):
 actor=_actor(claims)
 row=(await db.execute(text("select id,project_id,workspace_id,status from public.audio_generations where id=:id"),{"id":voiceover_id})).mappings().first()
 if row is None:raise HTTPException(404,"Voiceover job not found")
 await _scope(db,row["project_id"],actor,"project.update")
 if row["status"]!="queued":
  raise HTTPException(409,"Only queued voiceover jobs can be cancelled; running provider requests are not interrupted")
 await db.execute(text("update public.audio_generations set status='cancelled',completed_at=now() where id=:id and status='queued'"),{"id":voiceover_id})
 await release_fixed_operation(db,resource_type="voiceover",resource_id=voiceover_id,reason="user_cancelled_before_execution")
 await db.execute(text("""insert into public.audit_logs(actor_user_id,workspace_id,action,resource_type,resource_id,request_id)
  values(:actor,:workspace,'voiceover.cancelled','audio_generation',:id,:request_id)"""),
  {"actor":actor,"workspace":row["workspace_id"],"id":voiceover_id,"request_id":request.state.request_id})
 await db.commit()
 return {"data":{"voiceover_id":str(voiceover_id),"status":"cancelled"}}


@router.post("/internal/media-jobs/claim")
async def claim_media_job(request:Request,worker_id:str=Query(min_length=1,max_length=128),generation_id:UUID|None=Query(default=None),db:AsyncSession=DbSession):
 _require_worker(request)
 row=(await db.execute(text("select * from private.graphytion_claim_audio_generation(:worker,cast(:id as uuid))"),{"id":generation_id,"worker":worker_id})).mappings().first()
 if not row:await db.rollback();return {"data":None}
 await set_rls_subject(db,str(row["requested_by"]));await db.commit()
 return {"data":{"id":str(row["id"]),"project_id":str(row["project_id"]),"workspace_id":str(row["workspace_id"]),"requested_by":str(row["requested_by"]),"input_text":row["input_text"],"provider_key":row["provider_key"],"voice_key":row["voice_key"],"model_key":row["model_key"],"generation_config":row["generation_config"],"language":row["language"],"attempt_count":row["attempt_count"]}}
@router.post("/internal/media-jobs/{generation_id}/heartbeat")
async def heartbeat_media_job(generation_id:UUID,request:Request,worker_id:str=Query(min_length=1,max_length=128),db:AsyncSession=DbSession):
 _require_worker(request)
 owner=await db.scalar(text("select private.graphytion_heartbeat_media_job(:id,:worker)"),{"id":generation_id,"worker":worker_id})
 if not owner:raise HTTPException(409,"Media job lease is no longer owned")
 await set_rls_subject(db,str(owner));await db.commit();return {"data":{"generation_id":str(generation_id),"lease_extended":True}}
@router.post("/internal/media-jobs/{generation_id}/artifact",status_code=201)
async def complete_media_artifact(generation_id:UUID,request:Request,file:UploadFile,waveform_file:UploadFile|None=File(default=None),alignment_json:str|None=Form(default=None),media_metadata:str|None=Form(default=None),worker_id:str=Query(min_length=1,max_length=128),db:AsyncSession=DbSession):
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
 waveform_path=f"{row['workspace_id']}/{row['project_id']}/{asset_id}.waveform.json"
 waveform_content=await waveform_file.read(10*1024*1024+1) if waveform_file else b""
 if len(waveform_content)>10*1024*1024:raise HTTPException(413,"Waveform artifact exceeds 10 MB")
 try:
  alignment=json.loads(alignment_json) if alignment_json else {"status":"unavailable","provider":"unknown","reason":"alignment_not_supplied","words":[]}
  if alignment.get("status") not in {"available","unavailable"} or not isinstance(alignment.get("words"),list):raise ValueError("Invalid alignment result")
  metadata=json.loads(media_metadata) if media_metadata else None
  if metadata is not None and (not isinstance(metadata,dict) or not isinstance(metadata.get("duration_ms"),int) or metadata["duration_ms"]<=0):raise ValueError("Invalid audio metadata")
  await SupabaseStorage().upload(bucket=BUCKET,object_path=path,content=content,content_type="audio/mpeg",upsert=False,timeout_seconds=180)
  if waveform_content:
   if not metadata:raise ValueError("Waveform requires media metadata")
   waveform_hash=hashlib.sha256(waveform_content).hexdigest()
   await SupabaseStorage().upload(bucket=BUCKET,object_path=waveform_path,content=waveform_content,content_type="application/json",upsert=False,timeout_seconds=180)
  await db.execute(text("insert into public.project_assets(id,workspace_id,project_id,uploaded_by,bucket,object_path,file_name,content_type,size_bytes,sha256) values(:id,:workspace,:project,:actor,:bucket,:path,:name,'audio/mpeg',:size,:hash)"),{"id":asset_id,"workspace":row["workspace_id"],"project":row["project_id"],"actor":row["requested_by"],"bucket":BUCKET,"path":path,"name":"voiceover-"+str(generation_id)+".mp3","size":len(content),"hash":digest})
  await db.execute(text("update public.audio_generations set status='completed',asset_id=:asset,alignment_result=cast(:alignment as jsonb),alignment_status=:alignment_status,completed_at=now(),worker_id=null,lease_expires_at=null where id=:id"),{"asset":asset_id,"alignment":json.dumps(alignment),"alignment_status":alignment["status"],"id":generation_id})
  if waveform_content:
   await db.execute(text("""insert into public.audio_analysis_artifacts(workspace_id,project_id,audio_generation_id,audio_asset_id,waveform_bucket,waveform_path,waveform_sha256,media_metadata)
    values(:workspace,:project,:generation,:asset,:bucket,:path,:hash,cast(:metadata as jsonb))"""),{"workspace":row["workspace_id"],"project":row["project_id"],"generation":generation_id,"asset":asset_id,"bucket":BUCKET,"path":waveform_path,"hash":waveform_hash,"metadata":json.dumps(metadata)})
  segment_id=row["subtitle_segment_id"]
  if segment_id and alignment["status"]=="available":
   segment=(await db.execute(text("""select s.id,s.track_id,s.segment_index,s.start_ms,s.end_ms,s.text,s.speaker,s.word_timings,s.style_config,s.position_config,s.alignment_metadata,s.audio_asset_id,s.version,t.workspace_id
    from public.subtitle_segments s join public.subtitle_tracks t on t.id=s.track_id
    where s.id=:segment and t.project_id=:project and t.workspace_id=:workspace for update of s"""),{"segment":segment_id,"project":row["project_id"],"workspace":row["workspace_id"]})).mappings().first()
   if segment:
    aligned=[]
    for word in alignment["words"]:
     if not isinstance(word,dict) or not isinstance(word.get("start_ms"),int) or not isinstance(word.get("end_ms"),int) or not isinstance(word.get("text"),str):
      alignment["mapping_status"]="invalid_provider_word"
      aligned=[]
      break
     start=segment["start_ms"]+word["start_ms"];end=segment["start_ms"]+word["end_ms"]
     if not segment["start_ms"]<=start<end<=segment["end_ms"]:
      alignment["mapping_status"]="outside_segment_timing"
      aligned=[]
      break
     aligned.append({"text":word["text"],"start_ms":start,"end_ms":end,"audio_asset_id":str(asset_id),"provider":alignment.get("provider")})
    snapshot={"id":str(segment["id"]),"segment_index":segment["segment_index"],"start_ms":segment["start_ms"],"end_ms":segment["end_ms"],"text":segment["text"],"speaker":segment["speaker"],"word_timings":aligned,"style_config":segment["style_config"],"position_config":segment["position_config"],"alignment_metadata":{"provider":alignment.get("provider"),"audio_asset_id":str(asset_id)},"audio_asset_id":str(asset_id),"version":segment["version"]+1}
    revision=(await db.scalar(text("select coalesce(max(revision),0)+1 from public.subtitle_segment_revisions where segment_id=:id"),{"id":segment_id}))
    if aligned:
     await db.execute(text("""update public.subtitle_segments set audio_asset_id=:asset,word_timings=cast(:words as jsonb),
      alignment_metadata=cast(:metadata as jsonb),version=version+1,updated_at=now() where id=:id"""),{"asset":asset_id,"words":json.dumps(aligned),"metadata":json.dumps(snapshot["alignment_metadata"]),"id":segment_id})
     await db.execute(text("""insert into public.subtitle_segment_revisions(track_id,segment_id,revision,operation,snapshot,actor_user_id,request_id)
      values(:track,:segment,:revision,'regenerated',cast(:snapshot as jsonb),:actor,:request)"""),{"track":segment["track_id"],"segment":segment_id,"revision":revision,"snapshot":json.dumps(snapshot),"actor":row["requested_by"],"request":request.state.request_id})
  await reconcile_fixed_operation(db,resource_type="voiceover",resource_id=generation_id)
  await reconcile_fixed_operation(db,resource_type="voiceover",resource_id=generation_id)
  await db.commit()
 except Exception as exc:
  await db.rollback()
  for object_path in (path,waveform_path):
   try:await SupabaseStorage().remove(bucket=BUCKET,object_path=object_path)
   except Exception:pass
  raise HTTPException(502,"Voiceover artifact persistence failed") from exc
 return {"data":{"generation_id":str(generation_id),"asset_id":str(asset_id),"status":"completed","size_bytes":len(content),"sha256":digest,"alignment_status":alignment["status"],"waveform_persisted":bool(waveform_content)}}
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
 if not retry:
  await release_fixed_operation(db,resource_type="voiceover",resource_id=generation_id,reason=payload.error_code)
 await db.commit()
 # The worker discovers retryable rows through PostgreSQL polling.
 return {"data":{"generation_id":str(generation_id),"status":"queued" if retry else "failed"}}
@router.post("/internal/media-jobs/recover")
async def recover_media_jobs(request:Request,db:AsyncSession=DbSession):
 _require_worker(request)
 rows=(await db.execute(text("select private.graphytion_recover_audio_generations()"))).scalars().all()
 terminal=(await db.execute(text("""select q.id,a.requested_by from public.quota_reservations q
  join public.audio_generations a on a.id=q.resource_id
  where q.resource_type='voiceover' and q.status='reserved' and a.status in ('failed','cancelled')"""))).mappings().all()
 for item in terminal:
  await set_rls_subject(db,str(item["requested_by"]))
  await db.execute(text("select private.graphytion_release_quota(:id,'media_recovery_terminal')"),{"id":item["id"]})
 await db.commit()
 # Recovered queued rows are discovered by the worker on its next poll.
 return {"data":{"recovered_jobs":len(rows)}}
