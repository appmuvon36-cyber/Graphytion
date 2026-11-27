from __future__ import annotations
from typing import Any
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.supabase_storage import SupabaseStorage

ALLOWED_MIME={"image/png","image/jpeg","image/webp","image/svg+xml","video/mp4","audio/mpeg","audio/wav","font/woff2","font/woff","font/ttf","font/otf"}
async def resolve_project_assets(db:AsyncSession,*,project_id:UUID,workspace_id:UUID,asset_ids:list[UUID],expires_in:int=1800,snapshot:dict[str,Any]|None=None)->dict[str,str]:
 ids=list(dict.fromkeys(asset_ids))
 if len(ids)>500:raise HTTPException(422,"Composition references too many assets")
 if not ids:return {}
 rows=(await db.execute(text("""select id,bucket,object_path,content_type,status from public.project_assets where id=any(cast(:ids as uuid[])) and workspace_id=:workspace"""),{"ids":ids,"project":project_id,"workspace":workspace_id})).mappings().all()
 indexed={str(r["id"]):r for r in rows}
 if len(indexed)!=len(ids):raise HTTPException(422,"Composition references an asset outside this project")
 if snapshot:
  for clip in snapshot.get("clips",[]):
   key=clip["componentKey"];props=clip.get("props",{})
   media_id=props.get("assetId") or clip.get("assetId")
   if media_id:
    mime=indexed[str(UUID(str(media_id)))]["content_type"]
    expected={"visual.image.v1":{"image/png","image/jpeg","image/webp","image/svg+xml"},"visual.video.v1":{"video/mp4"},"audio.clip.v1":{"audio/mpeg","audio/wav"}}
    if key in expected and mime not in expected[key]:raise HTTPException(422,f"Asset type is incompatible with {key}")
   font_id=props.get("fontAssetId")
   if font_id and not indexed[str(UUID(str(font_id)))]["content_type"].startswith("font/"):raise HTTPException(422,"Typography font reference must point to a font asset")
  for ref in snapshot.get("assetRefs",[]):
   row=indexed[str(UUID(str(ref["assetId"])))]
   kind=ref.get("kind")
   if kind=="image" and not row["content_type"].startswith("image/"):raise HTTPException(422,"Image asset reference has an incompatible MIME type")
   if kind=="font" and not row["content_type"].startswith("font/"):raise HTTPException(422,"Font asset reference has an incompatible MIME type")
   if kind=="audio" and not row["content_type"].startswith("audio/"):raise HTTPException(422,"Audio asset reference has an incompatible MIME type")
   if kind=="video" and not row["content_type"].startswith("video/"):raise HTTPException(422,"Video asset reference has an incompatible MIME type")
 storage=SupabaseStorage();result={}
 for aid in ids:
  row=indexed[str(aid)]
  if row["status"]!="active" or row["content_type"] not in ALLOWED_MIME:raise HTTPException(422,f"Composition asset {aid} is unavailable or unsupported")
  try:result[str(aid)]=await storage.create_signed_url(bucket=row["bucket"],object_path=row["object_path"],expires_in=expires_in)
  except Exception as exc:raise HTTPException(502,"Private composition asset could not be resolved") from exc
 return result
def collect_asset_ids(snapshot:dict[str,Any])->list[UUID]:
 ids=[]
 for ref in snapshot.get("assetRefs",[]):
  try:ids.append(UUID(str(ref["assetId"])))
  except (KeyError,ValueError,TypeError) as exc:raise HTTPException(422,"Invalid composition asset reference") from exc
 for clip in snapshot.get("clips",[]):
  props=clip.get("props",{}) if isinstance(clip,dict) else {}
  for value in (clip.get("assetId") if isinstance(clip,dict) else None,props.get("assetId") if isinstance(props,dict) else None,props.get("fontAssetId") if isinstance(props,dict) else None):
   if value:
    try:ids.append(UUID(str(value)))
    except ValueError as exc:raise HTTPException(422,"Invalid composition asset UUID") from exc
 return list(dict.fromkeys(ids))
