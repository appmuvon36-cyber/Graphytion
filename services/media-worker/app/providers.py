from __future__ import annotations
from typing import Protocol
import httpx
class TTSProvider(Protocol):
 def configured(self)->bool: ...
 async def synthesize(self,*,text:str,voice:str,model:str)->tuple[bytes,str]: ...
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
