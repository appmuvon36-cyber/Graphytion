from __future__ import annotations
from typing import Any, Protocol
import httpx
class TTSProvider(Protocol):
 def configured(self)->bool: ...
 async def synthesize(self,*,text:str,voice:str,model:str)->tuple[bytes,str]: ...
 async def align_words(self,*,audio:bytes,filename:str='voiceover.mp3')->dict[str,Any]: ...
class OpenAITTSProvider:
 VOICES={"alloy","ash","coral","echo","fable","onyx","nova","sage","shimmer","verse"}
 def __init__(self,api_key:str):self.api_key=api_key
 def configured(self)->bool:return bool(self.api_key)
 async def synthesize(self,*,text:str,voice:str,model:str)->tuple[bytes,str]:
  if voice not in self.VOICES:raise ValueError("TTS_VOICE_UNSUPPORTED")
  if not self.api_key:raise RuntimeError("TTS_PROVIDER_NOT_CONFIGURED")
  async with httpx.AsyncClient(timeout=httpx.Timeout(180,connect=15)) as client:
   response=await client.post("https://api.openai.com/v1/audio/speech",headers={"Authorization":"Bearer "+self.api_key},json={"model":model,"voice":voice,"input":text,"response_format":"mp3"})
   response.raise_for_status();audio=response.content
  if not(audio.startswith(b"ID3") or (len(audio)>1 and audio[0]==0xFF and audio[1]&0xE0==0xE0)):raise RuntimeError("TTS_OUTPUT_INVALID")
  return audio,"audio/mpeg"
 async def align_words(self,*,audio:bytes,filename:str="voiceover.mp3")->dict[str,Any]:
  if not self.api_key:return {"status":"unavailable","provider":"openai","reason":"provider_not_configured","words":[]}
  async with httpx.AsyncClient(timeout=httpx.Timeout(180,connect=15)) as client:
   response=await client.post(
    "https://api.openai.com/v1/audio/transcriptions",
    headers={"Authorization":"Bearer "+self.api_key},
    data={"model":"whisper-1","response_format":"verbose_json","timestamp_granularities[]":"word"},
    files={"file":(filename,audio,"audio/mpeg")},
   )
   if response.status_code>=400:
    return {"status":"unavailable","provider":"openai","reason":"word_timestamp_provider_unavailable","http_status":response.status_code,"words":[]}
   payload=response.json()
  words=[]
  for item in payload.get("words",[]):
   start,end=item.get("start"),item.get("end")
   word=item.get("word")
   if isinstance(start,(int,float)) and isinstance(end,(int,float)) and 0<=start<end and isinstance(word,str) and word.strip():
    words.append({"text":word,"start_ms":round(start*1000),"end_ms":round(end*1000),"provider":"openai/whisper-1"})
  if not words:return {"status":"unavailable","provider":"openai","reason":"provider_returned_no_word_timestamps","words":[]}
  return {"status":"available","provider":"openai","model":"whisper-1","words":words}
