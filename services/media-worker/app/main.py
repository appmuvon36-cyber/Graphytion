from __future__ import annotations
import asyncio,json,logging,os,signal,socket,uuid
import httpx
from redis.asyncio import Redis
from app.providers import OpenAITTSProvider
from app.audio_analysis import analyze_audio_bytes

logging.basicConfig(level=os.environ.get("LOG_LEVEL","INFO"))
log=logging.getLogger("graphytion.media-worker")
API_BASE=os.environ.get("GRAPHYTION_API_BASE_URL","").rstrip("/")
TOKEN=os.environ.get("INTERNAL_WORKER_TOKEN","")
REDIS_URL=os.environ.get("REDIS_URL","redis://localhost:6379/0")
WORKER_ID=socket.gethostname()+"-"+uuid.uuid4().hex[:10]
STREAM="graphytion:media:tts";GROUP="graphytion-media-workers"

class Worker:
 def __init__(self):
  if not API_BASE or not TOKEN:raise RuntimeError("GRAPHYTION_API_BASE_URL and INTERNAL_WORKER_TOKEN are required")
  self.http=httpx.AsyncClient(base_url=API_BASE,headers={"Authorization":"Bearer "+TOKEN},timeout=httpx.Timeout(180,connect=15))
  self.redis=Redis.from_url(REDIS_URL,decode_responses=True)
  self.provider=OpenAITTSProvider(os.environ.get("OPENAI_API_KEY",""))
  self.model_default=os.environ.get("OPENAI_TTS_MODEL","tts-1")
  self.stop=asyncio.Event()
 async def api(self,path,**kwargs):
  response=await self.http.request(kwargs.pop("method","GET"),path.lstrip("/"),**kwargs)
  response.raise_for_status()
  body=response.json()
  return body.get("data",body)
 async def heartbeat(self,generation_id):
  while True:
   await asyncio.sleep(60)
   await self.api("/internal/media-jobs/"+generation_id+"/heartbeat",method="POST",params={"worker_id":WORKER_ID})
 async def fail(self,generation_id,code,retryable):
  try:await self.api("/internal/media-jobs/"+generation_id+"/failed",method="POST",params={"worker_id":WORKER_ID},json={"error_code":code,"retryable":retryable})
  except Exception:log.exception("media_job_failure_callback_failed",extra={"generation_id":generation_id})
 async def process(self,generation_id=None):
  try:job=await self.api("/internal/media-jobs/claim",method="POST",params={"worker_id":WORKER_ID,**({"generation_id":generation_id} if generation_id else {})})
  except Exception:log.exception("media_job_claim_failed");return
  if not job:return
  job_id=job["id"]
  if not self.provider.configured():
   await self.fail(job_id,"TTS_PROVIDER_NOT_CONFIGURED",False);return
  beat=asyncio.create_task(self.heartbeat(job_id))
  try:
   audio,mime=await self.provider.synthesize(text=job["input_text"],voice=job["voice_key"],model=job.get("model_key") or self.model_default)
   alignment=await self.provider.align_words(audio=audio)
   metadata,waveform=await asyncio.to_thread(analyze_audio_bytes,audio)
   await self.api("/internal/media-jobs/"+job_id+"/artifact",method="POST",params={"worker_id":WORKER_ID},
    data={"alignment_json":json.dumps(alignment),"media_metadata":json.dumps(metadata)},
    files={"file":("voiceover.mp3",audio,mime),"waveform_file":("waveform.json",waveform,"application/json")},
    timeout=httpx.Timeout(240,connect=15))
   log.info("voiceover_completed",extra={"generation_id":job_id,"bytes":len(audio)})
  except httpx.HTTPStatusError as exc:
   code="TTS_PROVIDER_HTTP_"+str(exc.response.status_code)
   await self.fail(job_id,code,exc.response.status_code>=500)
  except (httpx.TimeoutException,httpx.TransportError):
   await self.fail(job_id,"TTS_PROVIDER_NETWORK_ERROR",True)
  except ValueError as exc:
   await self.fail(job_id,str(exc) or "TTS_INVALID_REQUEST",False)
  except Exception:
   log.exception("voiceover_generation_failed",extra={"generation_id":job_id})
   await self.fail(job_id,"TTS_GENERATION_FAILED",True)
  finally:
   beat.cancel()
   try:await beat
   except asyncio.CancelledError:pass
   except Exception:log.exception("media_heartbeat_stopped")
 async def run(self):
  await self.redis.ping()
  try:await self.redis.xgroup_create(STREAM,GROUP,id="0",mkstream=True)
  except Exception as exc:
   if "BUSYGROUP" not in str(exc):raise
  log.info("media_worker_started",extra={"worker_id":WORKER_ID})
  while not self.stop.is_set():
   try:
    messages=await self.redis.xreadgroup(GROUP,WORKER_ID,{STREAM:">"},count=5,block=5000)
    for _,items in messages:
     for message_id,fields in items:
      await self.process(fields.get("generation_id"))
      await self.redis.xack(STREAM,GROUP,message_id)
    if not messages:
     await self.process()
     await self.api("/internal/media-jobs/recover",method="POST")
   except asyncio.CancelledError:raise
   except Exception:log.exception("media_worker_loop_failed");await asyncio.sleep(3)
 async def close(self):
  await self.http.aclose();await self.redis.aclose()

async def main():
 worker=Worker();loop=asyncio.get_running_loop()
 for sig in (signal.SIGINT,signal.SIGTERM):loop.add_signal_handler(sig,worker.stop.set)
 task=asyncio.create_task(worker.run());await worker.stop.wait();task.cancel()
 try:await task
 except asyncio.CancelledError:pass
 await worker.close()
if __name__=="__main__":asyncio.run(main())
