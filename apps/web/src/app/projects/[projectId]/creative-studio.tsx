'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiClientError, createApiClient } from '@graphytion/api-client';
import type {
  CreativeBriefApi, VideoScriptApi, StoryboardApi, VideoProjectApi, ProductionRunApi, RenderJobApi,
} from '@graphytion/contracts';

const apiBase = typeof window !== 'undefined' ? window.location.origin + '/api' : 'http://localhost:3000/api';
const field: React.CSSProperties = { width: '100%', padding: '11px 13px', border: '1px solid #dce3ed', borderRadius: 9, fontSize: 14, background: '#fff', color: '#142033' };
const button: React.CSSProperties = { border: 0, borderRadius: 9, padding: '10px 14px', background: '#173f72', color: '#fff', fontWeight: 700, cursor: 'pointer' };
type CreativeRunItem = ProductionRunApi;
type RenderItem = RenderJobApi;
const panel: React.CSSProperties = { background: '#fff', border: '1px solid #e5eaf1', borderRadius: 14, padding: 18, marginBottom: 14 };

export default function CreativeStudio({ projectId }: { projectId: string }) {
  const api = useMemo(() => createApiClient({ baseUrl: apiBase }), []);
  const [project, setProject] = useState<VideoProjectApi | null>(null);
  const [briefs, setBriefs] = useState<CreativeBriefApi[]>([]);
  const [scripts, setScripts] = useState<VideoScriptApi[]>([]);
  const [boards, setBoards] = useState<StoryboardApi[]>([]);
  const [runs, setRuns] = useState<CreativeRunItem[]>([]);
  const [renders, setRenders] = useState<RenderItem[]>([]);
  const [prompt, setPrompt] = useState('');
  const [briefJson, setBriefJson] = useState('{"objective":"","audience":"","key_message":"","tone":"","language":"id-ID","duration_target_ms":60000,"production_mode":"motion_graphic","visual_style":"","cta":"","constraints":[],"missing_information":[]}');
  const [scriptTitle, setScriptTitle] = useState('');
  const [scriptText, setScriptText] = useState('{"segments":[{"section":"hook","text":""},{"section":"narration","text":""},{"section":"cta","text":""}]}');
  const [sceneJson, setSceneJson] = useState('[{"scene_index":0,"title":"Opening","purpose":"Hook pembuka","narration_text":"","duration_ms":5000,"visual_direction":{"description":"","camera_angle":"wide","shot_type":"establishing","composition":"","movement":"","lighting":""},"motion_plan":{"transition":"fade"},"asset_requirements":[]} ]');
  const [selectedBrief, setSelectedBrief] = useState('');
  const [selectedScript, setSelectedScript] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const call = useCallback(async <T,>(path: string, init: RequestInit = {}) => {
    try { return await api.request<T>(path, init); }
    catch (e) {
      if (e instanceof ApiClientError && e.status === 401) setError('Sesi berakhir. Silakan masuk kembali ke Customer Studio.');
      throw e;
    }
  }, [api]);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [p, b, s, sb, runResult, renderResult] = await Promise.all([
        call<{data: VideoProjectApi}>('/projects/' + projectId),
        call<{data: CreativeBriefApi[]}>('/projects/' + projectId + '/briefs'),
        call<{data: VideoScriptApi[]}>('/projects/' + projectId + '/scripts'),
        call<{data: StoryboardApi[]}>('/projects/' + projectId + '/storyboards'),
        call<{data: CreativeRunItem[]}>('/projects/' + projectId + '/creative-runs'),
        call<{data: RenderItem[]}>('/projects/' + projectId + '/renders'),
      ]);
      setProject(p.data); setBriefs(b.data); setScripts(s.data); setBoards(sb.data);
      setRuns(runResult.data); setRenders(renderResult.data);
      if (!selectedBrief && b.data[0]) setSelectedBrief(b.data[0].id);
      if (!selectedScript && s.data[0]) setSelectedScript(s.data[0].id);
    } catch (e) { setError(e instanceof Error ? e.message : 'Gagal memuat creative workspace'); }
    finally { setLoading(false); }
  }, [call, projectId, selectedBrief, selectedScript]);

  useEffect(() => { void load(); }, [load]);

  async function generateStage(stage: 'brief' | 'script' | 'storyboard') {
    setBusy(true); setError(''); setNotice('');
    try {
      const body = stage === 'brief' ? { input_prompt: prompt }
        : stage === 'script' ? { brief_id: selectedBrief }
        : { script_id: selectedScript };
      const result = await call<{data:{run_id:string;status:string;artifact_type?:string}}>('/projects/' + projectId + '/creative-runs/' + stage, {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() }, body: JSON.stringify(body),
      });
      setNotice('Creative run ' + result.data.run_id + ' diterima dengan status ' + result.data.status + '.');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Creative generation tidak dapat dijalankan.');
    } finally { setBusy(false); }
  }

  async function createBrief(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError(''); setNotice('');
    try {
      const normalized = JSON.parse(briefJson) as Record<string, unknown>;
      const result = await call<{data: CreativeBriefApi}>('/projects/' + projectId + '/briefs', {
        method: 'POST', body: JSON.stringify({ input_prompt: prompt, normalized_brief: normalized }),
      });
      setSelectedBrief(result.data.id); setPrompt(''); setNotice('Creative brief tersimpan sebagai draft.'); await load();
    } catch (e) { setError(e instanceof Error ? e.message : 'Gagal menyimpan brief. Pastikan JSON valid.'); }
    finally { setBusy(false); }
  }

  async function approveBrief(id: string) {
    setBusy(true); setError('');
    try { await call('/projects/' + projectId + '/briefs/' + id + '/approve', { method: 'POST' }); setNotice('Brief disetujui.'); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Gagal menyetujui brief'); }
    finally { setBusy(false); }
  }

  async function createScript(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError(''); setNotice('');
    try {
      const body = JSON.parse(scriptText) as Record<string, unknown>;
      const brief = briefs.find(x => x.id === selectedBrief);
      const result = await call<{data: VideoScriptApi}>('/projects/' + projectId + '/scripts', {
        method: 'POST', body: JSON.stringify({
          brief_id: brief?.id || null, language: 'id-ID', title: scriptTitle, body,
        }),
      });
      setSelectedScript(result.data.id); setScriptTitle(''); setNotice('Script tersimpan sebagai draft.'); await load();
    } catch (e) { setError(e instanceof Error ? e.message : 'Gagal menyimpan script. Pastikan JSON valid.'); }
    finally { setBusy(false); }
  }

  async function approveScript(id: string) {
    setBusy(true); setError('');
    try { await call('/projects/' + projectId + '/scripts/' + id + '/approve', { method: 'POST' }); setNotice('Script disetujui. Storyboard dapat dibuat dari script ini.'); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Gagal menyetujui script'); }
    finally { setBusy(false); }
  }

  async function regenerateScene(sceneId: string) {
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await call<{data:{run_id:string;status:string}}>('/projects/' + projectId + '/creative-runs/scene', {
        method: 'POST',
        headers: { 'Idempotency-Key': crypto.randomUUID() },
        body: JSON.stringify({ scene_id: sceneId, revision_instruction: 'Improve visual storytelling, shot composition, lighting, and motion while preserving the approved narration and scene purpose.' }),
      });
      setNotice('Scene regeneration queued · ' + result.data.run_id);
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : 'Scene regeneration failed'); }
    finally { setBusy(false); }
  }

  async function approveStoryboard(id: string) {
    setBusy(true); setError('');
    try {
      await call('/projects/' + projectId + '/storyboards/' + id + '/approve', { method: 'POST' });
      setNotice('Storyboard approved.'); await load();
    } catch (e) { setError(e instanceof Error ? e.message : 'Storyboard approval failed'); }
    finally { setBusy(false); }
  }

  async function renderStoryboard(id: string) {
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await call<{data:{render_job_id:string;status:string}}>('/projects/' + projectId + '/storyboards/' + id + '/render', {
        method: 'POST', headers: { 'Idempotency-Key': crypto.randomUUID() },
      });
      setNotice('Render job queued · ' + result.data.render_job_id);
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : 'Render submission failed'); }
    finally { setBusy(false); }
  }

  async function downloadRender(id: string) {
    setError('');
    try {
      const result = await call<{data:{signed_url:string}}>('/renders/' + id + '/download');
      window.location.assign(result.data.signed_url);
    } catch (e) { setError(e instanceof Error ? e.message : 'Render download unavailable'); }
  }

  async function createStoryboard(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError(''); setNotice('');
    try {
      const parsed = JSON.parse(sceneJson) as Array<Record<string, unknown>>;
      const script = scripts.find(x => x.id === selectedScript);
      if (!script || script.status !== 'approved') throw new Error('Pilih script yang sudah disetujui.');
      const result = await call<{data: {storyboard: {id: string}}}>('/projects/' + projectId + '/storyboards', {
        method: 'POST', body: JSON.stringify({
          script_id: script.id,
          global_visual_direction: { visual_style: 'User-defined', aspect_ratio: project?.aspect_ratio || '16:9' },
          scenes: parsed,
        }),
      });
      setNotice('Storyboard tersimpan dengan ' + parsed.length + ' scene.'); await load();
    } catch (e) { setError(e instanceof Error ? e.message : 'Gagal menyimpan storyboard. Periksa JSON scene.'); }
    finally { setBusy(false); }
  }

  if (loading) return <main style={{maxWidth:1000,margin:'40px auto',padding:20}}><p>Memuat project dan creative artifacts…</p></main>;
  if (!project) return <main style={{maxWidth:760,margin:'40px auto',padding:20}}><p role="alert">{error || 'Project tidak ditemukan atau tidak dapat diakses.'}</p><a href="/">Kembali ke Studio</a></main>;

  return <main style={{maxWidth:1120,margin:'0 auto',padding:'30px 20px 70px'}}>
    <header style={{display:'flex',justifyContent:'space-between',gap:12,alignItems:'center',flexWrap:'wrap',marginBottom:22}}>
      <div><a href="/" style={{color:'#47719e',fontSize:13,textDecoration:'none'}}>← Customer Studio</a><p style={{fontSize:11,fontWeight:800,letterSpacing:'.14em',color:'#47719e',marginBottom:4}}>GRAPHYTION · CREATIVE WORKSPACE</p><h1 style={{fontSize:30,margin:'4px 0'}}>{project.name}</h1><p style={{color:'#68788e',margin:0}}>Brief → Script → Storyboard · {project.status}</p></div>
      <button onClick={() => void load()} disabled={busy} style={{...button,background:'#edf3f9',color:'#173f72'}}>Refresh data</button>
    </header>
    {error && <p role="alert" style={{padding:12,background:'#fff1f0',color:'#b42318',borderRadius:9}}>{error}</p>}
    {notice && <p role="status" style={{padding:12,background:'#ecfdf3',color:'#176b45',borderRadius:9}}>{notice}</p>}
    <section style={panel}>
      <h2 style={{marginTop:0}}>01 · Creative Brief</h2>
      <p style={{color:'#68788e',fontSize:13}}>Simpan brief terstruktur ke project. Penyimpanan ini tidak mengklaim bahwa AI telah menghasilkan atau menafsirkan prompt.</p>
      <form onSubmit={createBrief} style={{display:'grid',gap:9}}>
        <textarea aria-label="Prompt brief" placeholder="Tuliskan tujuan video, pesan utama, audiens, dan konteks…" value={prompt} onChange={e=>setPrompt(e.target.value)} required rows={4} style={field}/>
        <label style={{fontSize:13,fontWeight:700}}>Structured brief JSON</label>
        <textarea aria-label="Structured brief JSON" value={briefJson} onChange={e=>setBriefJson(e.target.value)} rows={6} style={{...field,fontFamily:'monospace',fontSize:12}}/>
        <div style={{display:"flex",gap:8,flexWrap:"wrap"}}><button disabled={busy} style={button}>Simpan brief draft</button><button type="button" disabled={busy||!prompt.trim()} onClick={()=>void generateStage("brief")} style={{...button,background:"#0d6b54"}}>Generate brief dengan AI</button></div>
      </form>
      <div style={{marginTop:16,display:'grid',gap:8}}>{briefs.map(b=><article key={b.id} style={{padding:12,border:'1px solid #edf0f5',borderRadius:10,display:'flex',justifyContent:'space-between',gap:10,flexWrap:'wrap'}}><div><strong>Brief v{b.version}</strong><p style={{fontSize:13,color:'#68788e',margin:'4px 0'}}>{b.input_prompt}</p><small>{b.status} · {new Date(b.created_at).toLocaleString()}</small></div><div style={{display:'flex',gap:8,alignItems:'center'}}><button type="button" onClick={()=>setSelectedBrief(b.id)} style={{...button,background:'#edf3f9',color:'#173f72'}}>Pilih</button>{b.status==='draft'&&<button type="button" disabled={busy} onClick={()=>void approveBrief(b.id)} style={button}>Approve</button>}</div></article>)}</div>
    </section>
    <section style={panel}>
      <h2 style={{marginTop:0}}>02 · Scriptwriter</h2>
      <p style={{color:'#68788e',fontSize:13}}>Buat dan kelola naskah versi draft. Script disimpan melalui FastAPI dan terkait ke brief terpilih.</p>
      <form onSubmit={createScript} style={{display:'grid',gap:9}}>
        <select aria-label="Creative brief" value={selectedBrief} onChange={e=>setSelectedBrief(e.target.value)} style={field}><option value="">Tanpa brief terpilih</option>{briefs.map(b=><option key={b.id} value={b.id}>Brief v{b.version} · {b.status}</option>)}</select>
        <input aria-label="Judul script" placeholder="Judul script" required value={scriptTitle} onChange={e=>setScriptTitle(e.target.value)} style={field}/>
        <label style={{fontSize:13,fontWeight:700}}>Script body JSON</label>
        <textarea aria-label="Script JSON" value={scriptText} onChange={e=>setScriptText(e.target.value)} rows={7} style={{...field,fontFamily:'monospace',fontSize:12}}/>
        <div style={{display:"flex",gap:8,flexWrap:"wrap"}}><button disabled={busy} style={button}>Simpan script draft</button><button type="button" disabled={busy||!briefs.some(b=>b.id===selectedBrief&&b.status==="approved")} onClick={()=>void generateStage("script")} style={{...button,background:"#0d6b54"}}>Generate script dengan AI</button></div>
      </form>
      <div style={{marginTop:16,display:'grid',gap:8}}>{scripts.map(s=><article key={s.id} style={{padding:12,border:'1px solid #edf0f5',borderRadius:10,display:'flex',justifyContent:'space-between',gap:10,flexWrap:'wrap'}}><div><strong>{s.title} · v{s.version}</strong><p style={{fontSize:13,color:'#68788e',margin:'4px 0'}}>{s.language} · {s.status} · {s.estimated_duration_ms ? Math.round(s.estimated_duration_ms/1000)+' detik' : 'Durasi belum ditentukan'}</p></div><div style={{display:'flex',gap:8,alignItems:'center'}}><button type="button" onClick={()=>setSelectedScript(s.id)} style={{...button,background:'#edf3f9',color:'#173f72'}}>Pilih</button>{s.status==='draft'&&<button type="button" disabled={busy} onClick={()=>void approveScript(s.id)} style={button}>Approve</button>}</div></article>)}</div>
    </section>
    <section style={panel}>
      <h2 style={{marginTop:0}}>03 · Storyboard & Visual Direction</h2>
      <p style={{color:'#68788e',fontSize:13}}>Storyboard hanya dapat dibuat dari script yang telah disetujui. Setiap scene menyimpan visual direction, shot, motion, transition, durasi, dan kebutuhan asset.</p>
      <form onSubmit={createStoryboard} style={{display:'grid',gap:9}}>
        <select aria-label="Approved script" value={selectedScript} onChange={e=>setSelectedScript(e.target.value)} style={field}><option value="">Pilih script disetujui</option>{scripts.filter(s=>s.status==='approved').map(s=><option key={s.id} value={s.id}>{s.title} · v{s.version}</option>)}</select>
        <label style={{fontSize:13,fontWeight:700}}>Storyboard scenes JSON</label>
        <textarea aria-label="Storyboard scenes JSON" value={sceneJson} onChange={e=>setSceneJson(e.target.value)} rows={10} style={{...field,fontFamily:'monospace',fontSize:12}}/>
        <div style={{display:"flex",gap:8,flexWrap:"wrap"}}><button disabled={busy||!scripts.some(s=>s.id===selectedScript&&s.status==='approved')} style={button}>Simpan storyboard</button><button type="button" disabled={busy||!scripts.some(s=>s.id===selectedScript&&s.status==='approved')} onClick={()=>void generateStage("storyboard")} style={{...button,background:"#0d6b54"}}>Generate storyboard dengan AI</button></div>
      </form>
      <div style={{marginTop:16,display:'grid',gap:8}}>{boards.map(b=><article key={b.id} style={{padding:12,border:'1px solid #edf0f5',borderRadius:10}}><div style={{display:'flex',justifyContent:'space-between',gap:8,alignItems:'center',flexWrap:'wrap'}}><strong>Storyboard v{b.version} · {b.scenes.length} scene</strong><div style={{display:'flex',gap:7}}>{b.status==='draft'&&<button type="button" disabled={busy} onClick={()=>void approveStoryboard(b.id)} style={button}>Approve</button>}{b.status==='approved'&&<button type="button" disabled={busy} onClick={()=>void renderStoryboard(b.id)} style={{...button,background:'#0d6b54'}}>Render MP4</button>}</div></div><p style={{fontSize:13,color:'#68788e',margin:'4px 0'}}>Script: {scripts.find(s=>s.id===b.script_id)?.title||b.script_id} · {b.status}</p>{b.scenes.map(sc=><div key={sc.id} style={{padding:'8px 0',borderTop:'1px solid #edf0f5',display:'flex',justifyContent:'space-between',alignItems:'center',gap:8,flexWrap:'wrap'}}><div><strong>{sc.scene_index+1}. {sc.title}</strong><p style={{fontSize:12,color:'#68788e',margin:'3px 0'}}>{sc.purpose||sc.narration_text||'No scene description'} · {Math.round(sc.duration_ms/1000)}s</p></div><button type="button" disabled={busy||b.status==='superseded'} onClick={()=>void regenerateScene(sc.id)} style={{...button,background:'#edf3f9',color:'#173f72'}}>Regenerate scene</button></div>)}</article>)}</div>
    </section>
    <section style={panel}>
      <h2 style={{marginTop:0}}>04 · Creative runs</h2>
      {runs.map(run=><div key={run.id} style={{padding:'8px 0',borderTop:'1px solid #edf0f5'}}><strong>{run.current_stage || 'Creative pipeline'} · {run.status}</strong><p style={{fontSize:12,color:'#68788e',margin:'3px 0'}}>Progress {run.progress_percent ?? 0}% · {run.error_code || run.id}</p></div>)}
      {runs.length===0&&<p style={{color:'#68788e'}}>Belum ada creative run.</p>}
    </section>
    <section style={panel}>
      <h2 style={{marginTop:0}}>05 · Render jobs</h2>
      {renders.map(render=><div key={render.id} style={{display:'flex',justifyContent:'space-between',alignItems:'center',gap:10,padding:'8px 0',borderTop:'1px solid #edf0f5',flexWrap:'wrap'}}><div><strong>{render.status}</strong><p style={{fontSize:12,color:'#68788e',margin:'3px 0'}}>Progress {render.progress_percent}% · {render.error_code || render.id}</p></div>{render.status==='completed'&&<button type="button" onClick={()=>void downloadRender(render.id)} style={button}>Download MP4</button>}</div>)}
      {renders.length===0&&<p style={{color:'#68788e'}}>Belum ada render job.</p>}
    </section>
    <p style={{fontSize:12,color:'#68788e'}}>AI generation berjalan melalui FastAPI Model Router dengan structured output, prompt version, dan persisted run lifecycle. Jika provider adapter belum diregistrasikan pada runtime, API mengembalikan status unavailable dan tidak membuat hasil AI palsu.</p>
  </main>;
}
