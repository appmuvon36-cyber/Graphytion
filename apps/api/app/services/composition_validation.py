from __future__ import annotations
from typing import Any
from uuid import UUID
from fastapi import HTTPException

COMPONENTS={
 "core.title-card.v1":("1.1.0","typography"),
 "visual.image.v1":("1.0.0","image"),
 "visual.video.v1":("1.0.0","video"),
 "visual.shape.v1":("1.0.0","shape"),
 "text.basic.v1":("1.0.0","typography"),
 "data.chart.v1":("1.0.0","chart"),
 "audio.clip.v1":("1.0.0","audio"),
 "text.subtitle.v1":("1.0.0","subtitle"),
}
PROPS={
 "core.title-card.v1":{"title","subtitle","background"},
 "visual.image.v1":{"assetId","fit","position","opacity","mask"},
 "visual.video.v1":{"assetId","fit","position","volume","playbackRate","trimStartFrames","muted"},
 "visual.shape.v1":{"shape","fill","stroke","strokeWidth","radius","shadow","points"},
 "text.basic.v1":{"text","fontFamily","fontAssetId","fontSize","fontWeight","color","align","letterSpacing","lineHeight","animation"},
 "data.chart.v1":{"chartType","data","color","showLabels"},
 "audio.clip.v1":{"assetId","volume","fadeInFrames","fadeOutFrames","playbackRate","trimStartFrames"},
 "text.subtitle.v1":{"text","color","background","fontSize","position","align"},
}
ASSET_COMPONENTS={"visual.image.v1":{"image/png","image/jpeg","image/webp","image/svg+xml"},"visual.video.v1":{"video/mp4"},"audio.clip.v1":{"audio/mpeg","audio/wav"}}
def _number(v:Any,lo:float,hi:float)->bool:return isinstance(v,(int,float)) and not isinstance(v,bool) and lo<=v<=hi
def validate_component(key:str,version:str,props:Any)->None:
 if key not in COMPONENTS or COMPONENTS[key][0]!=version:raise HTTPException(422,"Motion component key or schema version is unsupported")
 if not isinstance(props,dict) or set(props)-PROPS[key]:raise HTTPException(422,"Motion component props contain unsupported fields")
 if key=="core.title-card.v1" and (not isinstance(props.get("title"),str) or len(props["title"])>500):raise HTTPException(422,"Title card title is required and limited to 500 characters")
 if key in {"visual.image.v1","visual.video.v1","audio.clip.v1"}:
  try:UUID(str(props["assetId"]))
  except (KeyError,ValueError,TypeError) as exc:raise HTTPException(422,"Media component requires a valid project asset UUID") from exc
 if key=="visual.image.v1":
  if props.get("fit","contain") not in {"cover","contain","fill"} or props.get("mask","none") not in {"none","circle","rounded"} or not _number(props.get("opacity",1),0,1):raise HTTPException(422,"Image fit, mask or opacity is invalid")
 if key=="visual.video.v1":
  if props.get("fit","cover") not in {"cover","contain","fill"} or not _number(props.get("playbackRate",1),.1,4) or not _number(props.get("volume",1),0,1):raise HTTPException(422,"Video playback configuration is invalid")
 if key=="visual.shape.v1":
  if props.get("shape","rectangle") not in {"rectangle","circle","line","polygon"}:raise HTTPException(422,"Shape type is unsupported")
  if props.get("strokeWidth",0) and not _number(props["strokeWidth"],0,100):raise HTTPException(422,"Shape stroke width is invalid")
 if key=="text.basic.v1":
  if not isinstance(props.get("text"),str) or len(props["text"])>10000 or props.get("align","center") not in {"left","center","right","justify"}:raise HTTPException(422,"Typography content or alignment is invalid")
  if "fontAssetId" in props:
   try:UUID(str(props["fontAssetId"]))
   except ValueError as exc:raise HTTPException(422,"Font asset UUID is invalid") from exc
 if key=="data.chart.v1":
  data=props.get("data")
  if props.get("chartType","bar") not in {"bar","line","pie","progress"} or not isinstance(data,list) or not 1<=len(data)<=100:raise HTTPException(422,"Chart type or data is invalid")
  if any(not isinstance(p,dict) or not isinstance(p.get("label"),str) or not _number(p.get("value"),0,1e12) for p in data):raise HTTPException(422,"Chart data requires labels and non-negative numeric values")
 if key=="audio.clip.v1":
  for k in ("volume","fadeInFrames","fadeOutFrames","trimStartFrames"):
   if k in props and not _number(props[k],0,100000):raise HTTPException(422,f"Audio {k} is invalid")
  if not _number(props.get("playbackRate",1),.1,4):raise HTTPException(422,"Audio playback rate is invalid")
 if key=="text.subtitle.v1" and (not isinstance(props.get("text"),str) or not 1<=len(props["text"])<=4000):raise HTTPException(422,"Subtitle text is required and limited to 4,000 characters")
def validate_snapshot(snapshot:dict[str,Any])->str:
 import hashlib,json
 if snapshot.get("version")!=2 or snapshot.get("compositionVersion")!="2.0.0":raise HTTPException(422,"Unsupported composition snapshot version")
 fps,width,height,duration=snapshot.get("fps"),snapshot.get("width"),snapshot.get("height"),snapshot.get("durationFrames")
 if not isinstance(fps,int) or not 1<=fps<=120 or not isinstance(width,int) or not 320<=width<=7680 or not isinstance(height,int) or not 240<=height<=4320 or not isinstance(duration,int) or not 1<=duration<=fps*1800:raise HTTPException(422,"Composition timebase, dimensions or duration are invalid")
 tracks,clips,refs=snapshot.get("tracks"),snapshot.get("clips"),snapshot.get("assetRefs")
 if not isinstance(tracks,list) or not 1<=len(tracks)<=32 or not isinstance(clips,list) or len(clips)>500 or not isinstance(refs,list) or len(refs)>500:raise HTTPException(422,"Composition tracks, clips or asset references are invalid")
 track_map={}
 for track in tracks:
  if not isinstance(track,dict) or not isinstance(track.get("id"),str) or track["id"] in track_map:raise HTTPException(422,"Timeline track IDs must be unique")
  try: UUID(track["id"])
  except (ValueError,TypeError) as exc: raise HTTPException(422,"Timeline track ID must be a UUID") from exc
  if not isinstance(track.get("name"),str) or not 1<=len(track["name"])<=80:raise HTTPException(422,"Timeline track name is invalid")
  if track.get("kind") not in {"video","visual","shape","typography","audio","voiceover","subtitle","effects"} or not isinstance(track.get("zIndex"),int) or not isinstance(track.get("visible"),bool) or not isinstance(track.get("locked"),bool) or not isinstance(track.get("muted"),bool) or not _number(track.get("volume"),0,1):raise HTTPException(422,"Timeline track configuration is invalid")
  track_map[track["id"]]=track
 ids=set();asset_ids=set()
 for ref in refs:
  if not isinstance(ref,dict) or not isinstance(ref.get("assetId"),str) or ref.get("kind") not in {"image","video","audio","font","subtitle","resource"} or not isinstance(ref.get("required"),bool):raise HTTPException(422,"Invalid asset reference")
  try:asset_ids.add(str(UUID(ref["assetId"])))
  except ValueError as exc:raise HTTPException(422,"Invalid asset reference UUID") from exc
 for clip in clips:
  if not isinstance(clip,dict) or not isinstance(clip.get("id"),str) or clip["id"] in ids:raise HTTPException(422,"Clip IDs must be unique")
  ids.add(clip["id"])
  if clip.get("trackId") not in track_map or not isinstance(clip.get("startFrame"),int) or not isinstance(clip.get("durationFrames"),int) or clip["startFrame"]<0 or clip["durationFrames"]<1 or clip["startFrame"]+clip["durationFrames"]>duration:raise HTTPException(422,"Clip track or frame range is invalid")
  key,version,props=clip.get("componentKey"),clip.get("componentVersion"),clip.get("props")
  validate_component(key,version,props)
  track_kind=track_map[clip["trackId"]]["kind"]
  expected={"visual.image.v1":{"visual"},"visual.video.v1":{"video"},"visual.shape.v1":{"shape","visual"},"text.basic.v1":{"typography"},"core.title-card.v1":{"typography"},"data.chart.v1":{"shape","visual"},"audio.clip.v1":{"audio","voiceover"},"text.subtitle.v1":{"subtitle"}}
  if track_kind not in expected[key]:raise HTTPException(422,"Motion component is incompatible with its timeline track")
  if not isinstance(clip.get("trimStartFrames",0),int) or clip.get("trimStartFrames",0)<0 or not _number(clip.get("playbackRate",1),.1,4):raise HTTPException(422,"Clip trim or playback speed is invalid")
  for transition in (clip.get("transitionIn"),clip.get("transitionOut")):
   if transition is not None and (not isinstance(transition,dict) or transition.get("type") not in {"cut","fade","dissolve","crossfade","wipe","slide","zoom"} or not isinstance(transition.get("durationFrames"),int) or not 0<=transition["durationFrames"]<=clip["durationFrames"] or transition.get("direction","left") not in {"left","right","up","down"}):raise HTTPException(422,"Transition configuration is invalid")
  keyframes=clip.get("keyframes",{})
  if not isinstance(keyframes,dict) or set(keyframes)-{"opacity","scale","translateX","translateY","rotate","volume"}:raise HTTPException(422,"Keyframe properties are invalid")
  for property_name,frames in keyframes.items():
   if not isinstance(frames,list) or len(frames)>100:raise HTTPException(422,"Keyframe list is invalid")
   previous=-1
   for frame in frames:
    if not isinstance(frame,dict) or not isinstance(frame.get("frame"),int) or not 0<=frame["frame"]<=clip["durationFrames"] or frame["frame"]<=previous or not _number(frame.get("value"),-100000,100000) or frame.get("easing","linear") not in {"linear","ease-in","ease-out","ease-in-out"}:raise HTTPException(422,"Keyframes must be ordered, numeric and inside the clip duration")
    previous=frame["frame"]
  for field in ("assetId",):
   if clip.get(field):
    try:asset_ids.add(str(UUID(clip[field])))
    except ValueError as exc:raise HTTPException(422,"Invalid clip asset UUID") from exc
  if props.get("assetId"):asset_ids.add(str(UUID(props["assetId"])))
  if props.get("fontAssetId"):asset_ids.add(str(UUID(props["fontAssetId"])))
 canonical=json.dumps(snapshot,sort_keys=True,separators=(",",":"),ensure_ascii=False)
 return hashlib.sha256(canonical.encode()).hexdigest()
