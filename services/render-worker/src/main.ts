import {createClient} from 'redis';
import {makeCancelSignal, selectComposition, renderMedia} from '@remotion/renderer';
import {mkdtemp, readFile, rm, stat} from 'node:fs/promises';
import {execFile as execFileCallback} from 'node:child_process';
import {promisify} from 'node:util';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';

const redisUrl = process.env.REDIS_URL;
const apiBaseUrl = process.env.GRAPHYTION_API_BASE_URL ?? (() => { throw new Error('GRAPHYTION_API_BASE_URL is required'); })();
const workerToken = process.env.INTERNAL_WORKER_TOKEN;
const serveUrl = process.env.REMOTION_SERVE_URL ?? '/workspace/apps/remotion-studio/build';
if (!redisUrl) throw new Error('REDIS_URL is required');
if (!workerToken) throw new Error('INTERNAL_WORKER_TOKEN is required');
const execFile = promisify(execFileCallback);
const renderConcurrency = Number(process.env.REMOTION_RENDER_CONCURRENCY ?? 2);
const renderCrf = Number(process.env.REMOTION_RENDER_CRF ?? 18);
const x264Preset = process.env.REMOTION_X264_PRESET ?? 'medium';
if (!Number.isInteger(renderConcurrency) || renderConcurrency < 1 || renderConcurrency > 8) throw new Error('REMOTION_RENDER_CONCURRENCY must be between 1 and 8');
if (!Number.isInteger(renderCrf) || renderCrf < 0 || renderCrf > 51) throw new Error('REMOTION_RENDER_CRF must be between 0 and 51');
if (!['ultrafast','superfast','veryfast','faster','fast','medium','slow','slower','veryslow'].includes(x264Preset)) throw new Error('REMOTION_X264_PRESET is invalid');
const renderTimeoutMs = Number(process.env.RENDER_TIMEOUT_MS ?? 7200000);
if (!Number.isFinite(renderTimeoutMs) || renderTimeoutMs < 60000 || renderTimeoutMs > 86400000) {
  throw new Error('RENDER_TIMEOUT_MS must be between 60000 and 86400000');
}

const workerId = `render:${process.env.HOSTNAME ?? 'worker'}:${process.pid}:${randomUUID().slice(0, 8)}`;
const stream = 'graphytion:render:jobs';
const group = 'graphytion:render-workers';
const client = createClient({url: redisUrl});
client.on('error', error => console.error('redis_connection_error', error.message));

async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('Authorization', `Bearer ${workerToken}`);
  if (init.body && typeof init.body === 'string' && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const response = await fetch(new URL(path, apiBaseUrl.endsWith('/') ? apiBaseUrl : apiBaseUrl + '/'), {
    ...init,
    headers,
    cache: 'no-store',
    signal: init.signal ?? AbortSignal.timeout(30000),
  });
  const body = await response.json().catch(() => null) as {detail?: string; data?: T} | null;
  if (!response.ok) throw new Error(body?.detail ?? `Graphytion API returned HTTP ${response.status}`);
  return (body && typeof body === 'object' && 'data' in body ? body.data : body) as T;
}

type RenderJob = {
  id: string;
  composition_id: string;
  timeline_snapshot: {
    version: number; fps: number; width: number; height: number;
    durationFrames: number; tracks:Array<Record<string,unknown>>; clips: Array<Record<string, unknown>>; assetRefs:Array<Record<string,unknown>>; contentHash: string;
  };
  render_config: {codec?: string; format?: string; video_crf?:number; video_bitrate?:string|null; audio_codec?:string; audio_bitrate?:string|null; concurrency?:number};
  resolved_assets:Record<string,string>;
  attempt_count: number;
};

async function processJob(jobId?: string): Promise<boolean> {
  const query = new URLSearchParams({worker_id: workerId});
  if (jobId) query.set('render_job_id', jobId);
  const claimed = await api<RenderJob | null>(`internal/render-jobs/claim?${query.toString()}`, {method: 'POST'});
  if (!claimed) return false;

  const directory = await mkdtemp(join(tmpdir(), 'graphytion-render-'));
  const extension = claimed.render_config.format === 'webm' ? 'webm' : 'mp4';
  const outputPath = join(directory, `${claimed.id}.${extension}`);
  let lastProgressAt = 0;
  let currentProgress = 0;
  const {cancelSignal, cancel} = makeCancelSignal();
  let cancelInvoked = false;
  let timedOut = false;
  const cancelRender = () => { if (!cancelInvoked) { cancelInvoked = true; cancel(); } };
  const timeoutTimer = setTimeout(() => { timedOut = true; cancelRender(); }, renderTimeoutMs);
  const leaseHeartbeat = setInterval(async () => {
    try {
      const update = await api<{cancel_requested?: boolean}>(`internal/render-jobs/${claimed.id}/progress?worker_id=${encodeURIComponent(workerId)}`, {
        method: 'PATCH', body: JSON.stringify({progress_percent: Math.min(99.9, currentProgress)}),
      });
      if (update.cancel_requested) cancelRender();
    } catch (error) {
      console.error('render_lease_heartbeat_failed', {render_job_id: claimed.id, error});
      cancelRender();
    }
  }, 30000);
  try {
    const renderSnapshot = claimed.render_config.audio_codec === 'none' ? {...claimed.timeline_snapshot,tracks:claimed.timeline_snapshot.tracks.map(track => ['audio','voiceover'].includes(String(track.kind)) ? {...track,muted:true} : track)} : claimed.timeline_snapshot;
    const inputProps = {snapshot: renderSnapshot,resolvedAssets:claimed.resolved_assets};
    const composition = await selectComposition({
      serveUrl,
      id: claimed.composition_id,
      inputProps,
      browserExecutable: process.env.REMOTION_BROWSER_EXECUTABLE,
      timeoutInMilliseconds: 60000,
    });
    await renderMedia({
      composition,
      serveUrl,
      codec: claimed.render_config.codec === 'h265' || claimed.render_config.codec === 'vp8' || claimed.render_config.codec === 'vp9' ? claimed.render_config.codec : 'h264',
      outputLocation: outputPath,
      inputProps,
      cancelSignal,
      concurrency: claimed.render_config.concurrency ?? renderConcurrency,
      crf: claimed.render_config.video_crf ?? renderCrf,
      ...(claimed.render_config.video_bitrate ? {videoBitrate:claimed.render_config.video_bitrate} : {}),
      ...(claimed.render_config.audio_codec && claimed.render_config.audio_codec !== 'none' ? {audioCodec:claimed.render_config.audio_codec as 'aac'|'opus'} : {}),
      ...(claimed.render_config.audio_codec && claimed.render_config.audio_codec !== 'none' && claimed.render_config.audio_bitrate ? {audioBitrate:claimed.render_config.audio_bitrate as any} : {}),
      x264Preset: x264Preset as 'ultrafast'|'superfast'|'veryfast'|'faster'|'fast'|'medium'|'slow'|'slower'|'veryslow',
      pixelFormat: 'yuv420p',
      browserExecutable: process.env.REMOTION_BROWSER_EXECUTABLE,
      timeoutInMilliseconds: 60000,
      onProgress: ({progress}) => {
        currentProgress = Math.min(99.9, Math.max(0, progress * 100));
        const now = Date.now();
        if (progress >= 1 || now - lastProgressAt >= 5000) {
          lastProgressAt = now;
          void api<{cancel_requested?: boolean}>(`internal/render-jobs/${claimed.id}/progress?worker_id=${encodeURIComponent(workerId)}`, {
            method: 'PATCH',
            body: JSON.stringify({progress_percent: currentProgress}),
          }).then(update => {
            if (update.cancel_requested) cancelRender();
          }).catch(error => {
            console.error('render_progress_update_failed', {render_job_id: claimed.id, error});
            cancelRender();
          });
        }
      },
    });
    const probe = await execFile('ffprobe', ['-v','error','-show_entries','format=format_name,duration:stream=codec_type,codec_name,width,height','-of','json',outputPath], {timeout:30000, maxBuffer:1024*1024});
    const metadata = JSON.parse(probe.stdout) as {format?:{format_name?:string;duration?:string};streams?:Array<{codec_type?:string;codec_name?:string;width?:number;height?:number}>};
    const video = metadata.streams?.find(stream => stream.codec_type === 'video');
    const duration = Number(metadata.format?.duration);
    const expectedDuration = claimed.timeline_snapshot.durationFrames / claimed.timeline_snapshot.fps;
    const expectedCodec = ({h264:'h264',h265:'hevc',vp8:'vp8',vp9:'vp9'} as Record<string,string>)[claimed.render_config.codec ?? 'h264'];
    const formats = metadata.format?.format_name?.split(',') ?? [];
    const validContainer = extension === 'webm' ? formats.includes('webm') || formats.includes('matroska') : formats.includes('mp4');
    const audio = metadata.streams?.find(stream => stream.codec_type === 'audio');
    const expectedAudio = ({aac:'aac',opus:'opus'} as Record<string,string>)[claimed.render_config.audio_codec ?? 'aac'];
    if (!validContainer || video?.codec_name !== expectedCodec || video.width !== claimed.timeline_snapshot.width || video.height !== claimed.timeline_snapshot.height || !Number.isFinite(duration) || Math.abs(duration - expectedDuration) > (1 / claimed.timeline_snapshot.fps) + 0.05 || (claimed.render_config.audio_codec === 'none' && audio) || (claimed.render_config.audio_codec !== 'none' && audio && audio.codec_name !== expectedAudio)) throw new Error('Rendered media metadata does not match the immutable composition snapshot and profile');
    const outputStat = await stat(outputPath);
    if (outputStat.size < 12 || outputStat.size > 512 * 1024 * 1024) throw new Error('Rendered output size is outside the supported range');
    const bytes = await readFile(outputPath);
    const mime = extension === 'webm' ? 'video/webm' : 'video/mp4';
    const form = new FormData();
    form.set('file', new Blob([Uint8Array.from(bytes)], {type:mime}), 'output.'+extension);
    await api(`internal/render-jobs/${claimed.id}/artifact?worker_id=${encodeURIComponent(workerId)}`, {
      method: 'POST',
      body: form,
    });
    console.info('render_completed', {render_job_id: claimed.id, bytes: bytes.byteLength, duration_seconds: duration, width: video.width, height: video.height, codec: video.codec_name,container:extension});
    return true;
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown render worker error';
    try {
      await api(`internal/render-jobs/${claimed.id}/failed?worker_id=${encodeURIComponent(workerId)}`, {
        method: 'POST',
        body: JSON.stringify({
          error_code: timedOut ? 'REMOTION_RENDER_TIMEOUT' : 'REMOTION_RENDER_FAILED',
          error_message: message.slice(0, 500),
          retryable: !timedOut && claimed.attempt_count < 3,
        }),
      });
    } catch (callbackError) {
      console.error('render_failure_callback_failed', callbackError);
      throw callbackError;
    }
    console.error('render_failed', {render_job_id: claimed.id, message});
    return true;
  } finally {
    clearInterval(leaseHeartbeat);
    clearTimeout(timeoutTimer);
    await rm(directory, {recursive: true, force: true});
  }
}

async function main() {
  await client.connect();
  try {
    await client.xGroupCreate(stream, group, '0', {MKSTREAM: true});
  } catch (error) {
    if (!(error instanceof Error) || !error.message.includes('BUSYGROUP')) throw error;
  }
  console.info('graphytion_render_worker_started', {worker_id: workerId});
  let lastRecoveryScan = 0;
  while (true) {
    try {
      const batches = await client.xReadGroup(group, workerId, [{key: stream, id: '>'}], {
        COUNT: 1,
        BLOCK: 5000,
      }) as Array<{name:string;messages:Array<{id:string;message:Record<string,string>}>}> | null;
      for (const batch of batches ?? []) {
        for (const message of batch.messages) {
          const jobId = message.message.render_job_id;
          try {
            await processJob(jobId);
            await client.xAck(stream, group, message.id);
          } catch (error) {
            console.error('render_stream_message_failed', {id: message.id, error});
          }
        }
      }
      if (Date.now() - lastRecoveryScan >= 15000) {
        lastRecoveryScan = Date.now();
        await api('internal/render-jobs/recover', {method: 'POST'});
        await processJob();
      }
    } catch (error) {
      console.error('render_worker_loop_error', error);
      await new Promise(resolve => setTimeout(resolve, 2000));
    }
  }
}

async function shutdown() {
  if (client.isOpen) await client.quit();
  process.exit(0);
}
process.once('SIGINT', shutdown);
process.once('SIGTERM', shutdown);
await main();
