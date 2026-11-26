from __future__ import annotations
import json,re
from typing import Any
from uuid import UUID
from fastapi import APIRouter,HTTPException,Request
from pydantic import BaseModel,Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import AuthenticatedClaims,DbSession
from app.core.database import set_rls_subject
from app.services.workspace_authorization import WorkspacePermissionResolver

router=APIRouter();permissions=WorkspacePermissionResolver()
class SubtitleSegmentInput(BaseModel):
 segment_index:int=Field(ge=0)
 start_ms:int=Field(ge=0)
 end_ms:int=Field(gt=0)
 text:str=Field(min_length=1,max_length=4000)
 speaker:str|None=Field(default=None,max_length=120)
 word_timings:list[dict[str,Any]]=Field(default_factory=list)
class SubtitleTrackInput(BaseModel):
 language:str=Field(default="id-ID",min_length=2,max_length=16)
 format:str=Field(default="webvtt",pattern=r"^(webvtt|srt)$")
 style_config:dict[str,Any]=Field(default_factory=dict)
 segments:list[SubtitleSegmentInput]=Field(default_factory=list,max_length=5000)
class SubtitleImport(BaseModel):
 language:str=Field(default="id-ID",min_length=2,max_length=16)
 format:str=Field(pattern=r"^(webvtt|srt)$")
 content:str=Field(min_length=1,max_length=2_000_000)
 style_config:dict[str,Any]=Field(default_factory=dict)
def _actor(claims:dict[str,Any])->UUID:
 try:return UUID(str(claims["sub"]))
 except (KeyError,ValueError,TypeError) as exc:raise HTTPException(401,"Invalid authenticated subject") from exc
async def _scope(db:AsyncSession,project:UUID,actor:UUID,permission:str)->UUID:
 workspace=await db.scalar(text("select workspace_id from public.video_projects where id=:id and status<>'deleted'"),{"id":project})
 if not workspace:raise HTTPException(404,"Project not found")
 await permissions.require_permission(session=db,user_id=str(actor),workspace_id=str(workspace),permission=permission)
 await set_rls_subject(db,str(actor));return workspace
def _validate_segments(segments:list[SubtitleSegmentInput])->None:
 previous=-1
 for item in segments:
  if item.end_ms<=item.start_ms or item.start_ms<previous:raise HTTPException(422,"Subtitle segments must have positive duration and be ordered by start time")
  if len(item.word_timings)>500:raise HTTPException(422,"Too many word timing entries")
  for word in item.word_timings:
   if not isinstance(word,dict) or not isinstance(word.get("start_ms"),int) or not isinstance(word.get("end_ms"),int) or not item.start_ms<=word["start_ms"]<word["end_ms"]<=item.end_ms or not isinstance(word.get("text"),str):
    raise HTTPException(422,"Subtitle word timings must be contained within their segment")
  previous=item.start_ms
def _timestamp(ms:int,comma:bool)->str:
 h,rem=divmod(ms,3600000);m,rem=divmod(rem,60000);sec,milli=divmod(rem,1000)
 return f"{h:02d}:{m:02d}:{sec:02d}{',' if comma else '.'}{milli:03d}"
def _parse_timestamp(value:str)->int:
 match=re.fullmatch(r"(?:(\d{2}):)?(\d{2}):(\d{2})[,.](\d{1,3})",value.strip())
 if not match:raise HTTPException(422,"Invalid subtitle timestamp")
 h,m,sec,ms=match.groups();return ((int(h or 0)*60+int(m))*60+int(sec))*1000+int(ms.ljust(3,"0"))
def _parse(content:str,fmt:str)->list[SubtitleSegmentInput]:
 raw=content.replace("\r\n","\n").replace("\r","\n").strip()
 if fmt=="webvtt":
  if not raw.startswith("WEBVTT"):raise HTTPException(422,"WebVTT header is required")
  raw=raw.split("\n",1)[1] if "\n" in raw else ""
 blocks=re.split(r"\n\s*\n",raw);segments=[]
 for block in blocks:
  lines=[x.strip("\ufeff") for x in block.strip().split("\n") if x.strip()]
  timing=next((i for i,line in enumerate(lines) if "-->" in line),None)
  if timing is None:continue
  left,right=[x.strip().split(" ")[0] for x in lines[timing].split("-->",1)]
  start,end=_parse_timestamp(left),_parse_timestamp(right)
  text_value="\n".join(lines[timing+1:]).strip()
  if text_value:segments.append(SubtitleSegmentInput(segment_index=len(segments),start_ms=start,end_ms=end,text=re.sub(r"<[^>]+>","",text_value)))
 if not segments:raise HTTPException(422,"No valid subtitle segments were found")
 _validate_segments(segments);return segments
def _export(segments:list[dict[str,Any]],fmt:str)->str:
 rows=[]
 if fmt=="webvtt":rows.append("WEBVTT")
 for i,item in enumerate(segments):
  if fmt=="srt":rows.append(str(i+1))
  rows.append(_timestamp(item["start_ms"],fmt=="srt")+" --> "+_timestamp(item["end_ms"],fmt=="srt"))
  rows.append(item["text"])
  rows.append("")
 return "\n".join(rows).strip()+"\n"
async def _create(db:AsyncSession,project:UUID,workspace:UUID,actor:UUID,payload:SubtitleTrackInput,request:Request):
 _validate_segments(payload.segments)
 track=(await db.execute(text("""insert into public.subtitle_tracks(workspace_id,project_id,language,format,style_config,created_by)
 values(:workspace,:project,:language,:format,cast(:style as jsonb),:actor) returning id,version,created_at"""),{"workspace":workspace,"project":project,"language":payload.language,"format":payload.format,"style":json.dumps(payload.style_config),"actor":actor})).mappings().one()
 for seg in payload.segments:
  await db.execute(text("""insert into public.subtitle_segments(track_id,segment_index,start_ms,end_ms,text,speaker,word_timings)
 values(:track,:idx,:start,:end,:text,:speaker,cast(:words as jsonb))"""),{"track":track["id"],"idx":seg.segment_index,"start":seg.start_ms,"end":seg.end_ms,"text":seg.text,"speaker":seg.speaker,"words":json.dumps(seg.word_timings)})
 await db.execute(text("insert into public.audit_logs(actor_user_id,workspace_id,action,resource_type,resource_id,request_id) values(:actor,:workspace,'subtitle_track.created','subtitle_track',:id,:request)"),{"actor":actor,"workspace":workspace,"id":track["id"],"request":request.state.request_id})
 await db.commit();return track
@router.get("/projects/{project_id}/subtitles")
async def list_subtitle_tracks(project_id:UUID,claims:AuthenticatedClaims,db:AsyncSession=DbSession):
 actor=_actor(claims);workspace=await _scope(db,project_id,actor,"project.read")
 tracks=(await db.execute(text("select id,language,format,version,style_config,created_at from public.subtitle_tracks where project_id=:project and workspace_id=:workspace order by created_at desc"),{"project":project_id,"workspace":workspace})).mappings().all()
 result=[]
 for track in tracks:
  segments=(await db.execute(text("select id,segment_index,start_ms,end_ms,text,speaker,word_timings from public.subtitle_segments where track_id=:id order by segment_index"),{"id":track["id"]})).mappings().all()
  result.append({**dict(track),"segments":[dict(x) for x in segments]})
 return {"data":result}
@router.post("/projects/{project_id}/subtitles",status_code=201)
async def create_subtitle_track(project_id:UUID,payload:SubtitleTrackInput,request:Request,claims:AuthenticatedClaims,db:AsyncSession=DbSession):
 actor=_actor(claims);workspace=await _scope(db,project_id,actor,"project.update");track=await _create(db,project_id,workspace,actor,payload,request)
 return {"data":{"id":str(track["id"]),"version":track["version"],"created_at":track["created_at"]}}
@router.put("/projects/{project_id}/subtitles/{track_id}")
async def update_subtitle_track(project_id:UUID,track_id:UUID,payload:SubtitleTrackInput,request:Request,claims:AuthenticatedClaims,db:AsyncSession=DbSession):
 actor=_actor(claims);workspace=await _scope(db,project_id,actor,"project.update");_validate_segments(payload.segments)
 track=(await db.execute(text("select id from public.subtitle_tracks where id=:id and project_id=:project and workspace_id=:workspace for update"),{"id":track_id,"project":project_id,"workspace":workspace})).first()
 if not track:raise HTTPException(404,"Subtitle track not found")
 await db.execute(text("delete from public.subtitle_segments where track_id=:id"),{"id":track_id})
 for seg in payload.segments:
  await db.execute(text("insert into public.subtitle_segments(track_id,segment_index,start_ms,end_ms,text,speaker,word_timings) values(:track,:idx,:start,:end,:text,:speaker,cast(:words as jsonb))"),{"track":track_id,"idx":seg.segment_index,"start":seg.start_ms,"end":seg.end_ms,"text":seg.text,"speaker":seg.speaker,"words":json.dumps(seg.word_timings)})
 await db.execute(text("update public.subtitle_tracks set language=:language,format=:format,style_config=cast(:style as jsonb),version=version+1 where id=:id"),{"language":payload.language,"format":payload.format,"style":json.dumps(payload.style_config),"id":track_id})
 await db.execute(text("insert into public.audit_logs(actor_user_id,workspace_id,action,resource_type,resource_id,request_id) values(:actor,:workspace,'subtitle_track.updated','subtitle_track',:id,:request)"),{"actor":actor,"workspace":workspace,"id":track_id,"request":request.state.request_id})
 await db.commit();return {"data":{"id":str(track_id),"status":"updated"}}
@router.post("/projects/{project_id}/subtitles/import",status_code=201)
async def import_subtitles(project_id:UUID,payload:SubtitleImport,request:Request,claims:AuthenticatedClaims,db:AsyncSession=DbSession):
 actor=_actor(claims);workspace=await _scope(db,project_id,actor,"project.update");segments=_parse(payload.content,payload.format)
 track=await _create(db,project_id,workspace,actor,SubtitleTrackInput(language=payload.language,format=payload.format,style_config=payload.style_config,segments=segments),request)
 return {"data":{"id":str(track["id"]),"version":track["version"],"segment_count":len(segments)}}
@router.get("/projects/{project_id}/subtitles/{track_id}/export")
async def export_subtitles(project_id:UUID,track_id:UUID,claims:AuthenticatedClaims,db:AsyncSession=DbSession):
 actor=_actor(claims);workspace=await _scope(db,project_id,actor,"project.read")
 track=(await db.execute(text("select id,format,language from public.subtitle_tracks where id=:id and project_id=:project and workspace_id=:workspace"),{"id":track_id,"project":project_id,"workspace":workspace})).mappings().first()
 if not track:raise HTTPException(404,"Subtitle track not found")
 segments=(await db.execute(text("select start_ms,end_ms,text from public.subtitle_segments where track_id=:id order by segment_index"),{"id":track_id})).mappings().all()
 return {"data":{"format":track["format"],"language":track["language"],"content":_export([dict(x) for x in segments],track["format"])}}
