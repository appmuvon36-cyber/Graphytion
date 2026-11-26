import {createClient} from 'redis';
import {makeCancelSignal, selectComposition, renderMedia} from '@remotion/renderer';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';

const redisUrl = process.env.REDIS_URL;
const apiBaseUrl = process.env.GRAPHYTION_API_BASE_URL;
const workerToken = process.env.INTERNAL_WORKER_TOKEN;
const serveUrl = process.env.REMOTION_SERVE_URL;
if (!redisUrl) throw new Error('REDIS_URL is required');
if (!apiBaseUrl) throw new Error('GRAPHYTION_API_BASE_URL is required');
if (!workerToken) throw new Error('INTERNAL_WORKER_TOKEN is required');
if (!serveUrl) throw new Error('REMOTION_SERVE_URL is required');
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
    durationFrames: number; clips: Array<Record<string, unknown>>; contentHash: string;
  };
  render_config: {codec?: string; format?: string};
  attempt_count: number;
};

async function processJob(jobId?: string): Promise<boolean> {
  const query = new URLSearchParams({worker_id: workerId});
  if (jobId) query.set('render_job_id', jobId);
  const claimed = await api<RenderJob | null>(`internal/render-jobs/claim?${query.toString()}`, {method: 'POST'});
  if (!claimed) return false;

  const directory = await mkdtemp(join(tmpdir(), 'graphytion-render-'));
  const outputPath = join(directory, `${claimed.id}.mp4`);
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
    const inputProps = {snapshot: claimed.timeline_snapshot};
    const composition = await selectComposition({
      serveUrl,
      id: claimed.composition_id,
      inputProps,
    });
    await renderMedia({
      composition,
      serveUrl,
      codec: 'h264',
      outputLocation: outputPath,
      inputProps,
      cancelSignal,
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
    const bytes = await readFile(outputPath);
    const form = new FormData();
    form.set('file', new Blob([Uint8Array.from(bytes)], {type: 'video/mp4'}), 'output.mp4');
    await api(`internal/render-jobs/${claimed.id}/artifact?worker_id=${encodeURIComponent(workerId)}`, {
      method: 'POST',
      body: form,
    });
    console.info('render_completed', {render_job_id: claimed.id, bytes: bytes.byteLength});
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
      });
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
