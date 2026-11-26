'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiClientError, createApiClient } from '@graphytion/api-client';
import { TimelineEditor } from '@graphytion/motion-components';
import type {CompositionSnapshot,ResolvedCompositionAssets} from '@graphytion/motion-components';
import type {
  CreativeBriefApi, VideoScriptApi, StoryboardApi, VideoProjectApi, ProductionRunApi, RenderJobApi, ProjectAssetApi,
} from '@graphytion/contracts';

const apiBase = typeof window !== 'undefined' ? window.location.origin + '/api' : 'http://localhost:3000/api';
const field: React.CSSProperties = { width: '100%', padding: '11px 13px', border: '1px solid #dce3ed', borderRadius: 9, fontSize: 14, background: '#fff', color: '#142033' };
const button: React.CSSProperties = { border: 0, borderRadius: 9, padding: '10px 14px', background: '#173f72', color: '#fff', fontWeight: 700, cursor: 'pointer' };
type CreativeRunItem = ProductionRunApi;
type RenderItem = RenderJobApi;
type VoiceoverItem={id:string;scene_id?:string|null;provider_key:string;model_key:string;voice_key:string;language:string;status:string;asset_id?:string|null;error_code?:string|null;attempt_count:number};
type SubtitleSegmentItem={id:string;segment_index:number;start_ms:number;end_ms:number;text:string;speaker?:string|null;word_timings?:Array<Record<string,unknown>>;version?:number;style_config?:Record<string,unknown>;position_config?:Record<string,unknown>;alignment_metadata?:Record<string,unknown>;audio_asset_id?:string|null};
type SubtitleTrackItem={id:string;language:string;format:'webvtt'|'srt';version:number;style_config:Record<string,unknown>;segments:SubtitleSegmentItem[]};
type TimelineHistoryItem={id:string;version:number;compiled_hash:string;created_at:string;fps:number;width:number;height:number;duration_frames:number};

const panel: React.CSSProperties = { background: '#fff', border: '1px solid #e5eaf1', borderRadius: 14, padding: 18, marginBottom: 14 };

export default function CreativeStudio({ projectId }: { projectId: string }) {
  const api = useMemo(() => createApiClient({ baseUrl: apiBase }), []);
  const [project, setProject] = useState<VideoProjectApi | null>(null);
  const [briefs, setBriefs] = useState<CreativeBriefApi[]>([]);
  const [scripts, setScripts] = useState<VideoScriptApi[]>([]);
  const [boards, setBoards] = useState<StoryboardApi[]>([]);
  const [runs, setRuns] = useState<CreativeRunItem[]>([]);
  const [renders, setRenders] = useState<RenderItem[]>([]);
  const [previewSnapshot, setPreviewSnapshot] = useState<CompositionSnapshot | null>(null);
  const [previewResolvedAssets,setPreviewResolvedAssets]=useState<ResolvedCompositionAssets>({});
  const [timelineVersion,setTimelineVersion]=useState<number|null>(null);
  const [timelineHistory,setTimelineHistory]=useState<TimelineHistoryItem[]>([]);
  const [timelineDirty,setTimelineDirty]=useState(false);
  const [timelineSaving,setTimelineSaving]=useState(false);
  const [previewStoryboardId, setPreviewStoryboardId] = useState('');
  const [assets, setAssets] = useState<ProjectAssetApi[]>([]);
  const [voiceovers,setVoiceovers]=useState<VoiceoverItem[]>([]);
  const [subtitleTracks,setSubtitleTracks]=useState<SubtitleTrackItem[]>([]);
  const [subtitleDrafts,setSubtitleDrafts]=useState<Record<string,{text:string;start_ms:number;end_ms:number}>>({});
  const [selectedSubtitleSegments,setSelectedSubtitleSegments]=useState<string[]>([]);
  const [voiceText,setVoiceText]=useState('');
  const [voiceProvider,setVoiceProvider]=useState<'gemini'|'openai'>('gemini');
  const [voiceKey,setVoiceKey]=useState('Kore');
  const [voiceModel,setVoiceModel]=useState('gemini-3.8-flash-lite-tts');
  const [selectedVoiceSubtitleSegmentId,setSelectedVoiceSubtitleSegmentId]=useState('');
  const [newSubtitleText,setNewSubtitleText]=useState('');
  const [subtitleImport,setSubtitleImport]=useState('');
  const [subtitleFormat,setSubtitleFormat]=useState<'srt'|'webvtt'>('srt');
  const [assetFile, setAssetFile] = useState<File | null>(null);
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
      const [p, b, s, sb, runResult, renderResult, assetResult, voiceResult, subtitleResult] = await Promise.all([
        call<{data: VideoProjectApi}>('/projects/' + projectId),
        call<{data: CreativeBriefApi[]}>('/projects/' + projectId + '/briefs'),
        call<{data: VideoScriptApi[]}>('/projects/' + projectId + '/scripts'),
        call<{data: StoryboardApi[]}>('/projects/' + projectId + '/storyboards'),
        call<{data: CreativeRunItem[]}>('/projects/' + projectId + '/creative-runs'),
        call<{data: RenderItem[]}>('/projects/' + projectId + '/renders'),
        call<{data: ProjectAssetApi[]}>('/projects/' + projectId + '/assets'),
        call<{data:VoiceoverItem[]}>('/projects/'+projectId+'/voiceovers'),
        call<{data:SubtitleTrackItem[]}>('/projects/'+projectId+'/subtitles'),
      ]);
      setProject(p.data); setBriefs(b.data); setScripts(s.data); setBoards(sb.data);
      setRuns(runResult.data); setRenders(renderResult.data); setAssets(assetResult.data); setVoiceovers(voiceResult.data); setSubtitleTracks(subtitleResult.data);
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

  async function uploadAsset(event: React.FormEvent) {
    event.preventDefault();
    if (!assetFile) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const form = new FormData();
      form.set('file', assetFile);
      await call('/projects/' + projectId + '/assets', { method: 'POST', body: form });
      setAssetFile(null); setNotice('Project asset uploaded and registered.'); await load();
    } catch (e) { setError(e instanceof Error ? e.message : 'Asset upload failed'); }
    finally { setBusy(false); }
  }

  async function downloadAsset(asset: ProjectAssetApi) {
    setError('');
    try {
      const result = await call<{data:{signed_url:string}}>('/assets/' + asset.id + '/download');
      window.location.assign(result.data.signed_url);
    } catch (e) { setError(e instanceof Error ? e.message : 'Asset download unavailable'); }
  }

  async function deleteAsset(asset: ProjectAssetApi) {
    if (!window.confirm('Delete asset ' + asset.file_name + '?')) return;
    setBusy(true); setError('');
    try {
      await call('/assets/' + asset.id, { method: 'DELETE' });
      setNotice('Project asset deleted from private storage.'); await load();
    } catch (e) { setError(e instanceof Error ? e.message : 'Asset deletion failed'); }
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

  async function previewStoryboard(id: string) {
    setBusy(true); setError(''); setNotice('');
    try {
      const [result,history] = await Promise.all([
        call<{data:{snapshot:CompositionSnapshot;resolved_assets:ResolvedCompositionAssets}}>('/projects/' + projectId + '/storyboards/' + id + '/preview'),
        call<{data:TimelineHistoryItem[]}>('/projects/'+projectId+'/timelines'),
      ]);
      setPreviewSnapshot(result.data.snapshot); setPreviewResolvedAssets(result.data.resolved_assets||{});
      setTimelineHistory(history.data);setTimelineVersion(history.data[0]?.version??null);setTimelineDirty(true);
      setPreviewStoryboardId(id);
      setNotice('Preview memakai timeline snapshot yang sama dengan renderer Remotion.');
    } catch (e) { setError(e instanceof Error ? e.message : 'Remotion preview failed'); }
    finally { setBusy(false); }
  }

  async function retryVoiceover(item:VoiceoverItem) {
    setBusy(true);setError('');
    try{await call('/voiceovers/'+item.id+'/retry',{method:'POST'});setNotice('Voiceover job re-queued.');await load();}
    catch(e){setError(e instanceof Error?e.message:'Voiceover retry failed');}
    finally{setBusy(false);}
  }
  async function generateVoiceover(event:React.FormEvent) {
    event.preventDefault();setBusy(true);setError('');setNotice('');
    try{
      const result=await call<{data:{voiceover_id:string;status:string;provider_configured:boolean}}>('/projects/'+projectId+'/voiceovers',{
        method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()},
        body:JSON.stringify({text:voiceText,provider_key:voiceProvider,model_key:voiceModel,voice_key:voiceKey,language:project?.default_language||'id-ID',...(selectedVoiceSubtitleSegmentId?{subtitle_segment_id:selectedVoiceSubtitleSegmentId}:{})}),
      });
      setNotice(result.data.status==='provider_unavailable'?'Voiceover job tersimpan, tetapi provider credentials belum dikonfigurasi. Tidak ada audio yang dibuat.':'Voiceover job queued · '+result.data.voiceover_id);
      await load();
    }catch(e){setError(e instanceof Error?e.message:'Voiceover request failed');}
    finally{setBusy(false);}
  }
  function updateSubtitleDraft(segment:SubtitleSegmentItem,patch:Partial<{text:string;start_ms:number;end_ms:number}>) {
    setSubtitleDrafts(current=>({...current,[segment.id]:{text:current[segment.id]?.text??segment.text,start_ms:current[segment.id]?.start_ms??segment.start_ms,end_ms:current[segment.id]?.end_ms??segment.end_ms,...patch}}));
  }
  async function createSubtitleSegment(track:SubtitleTrackItem) {
    const start=track.segments.length?Math.max(...track.segments.map(item=>item.end_ms)):0;
    if(!newSubtitleText.trim())return;
    setBusy(true);setError('');
    try {
      await call('/projects/'+projectId+'/subtitles/'+track.id+'/segments',{
        method:'POST',body:JSON.stringify({segment_index:track.segments.length,start_ms:start,end_ms:start+2000,text:newSubtitleText.trim()}),
      });
      setNewSubtitleText('');setNotice('New subtitle segment created.');await load();
    } catch(e) {setError(e instanceof Error?e.message:'Subtitle segment creation failed');}
    finally {setBusy(false);}
  }
  async function saveSubtitleSegment(track:SubtitleTrackItem,segment:SubtitleSegmentItem) {
    const draft=subtitleDrafts[segment.id]??{text:segment.text,start_ms:segment.start_ms,end_ms:segment.end_ms};
    setBusy(true);setError('');
    try {
      await call('/projects/'+projectId+'/subtitles/'+track.id+'/segments/'+segment.id,{
        method:'PATCH',body:JSON.stringify(draft),
      });
      setSubtitleDrafts(current=>{const next={...current};delete next[segment.id];return next;});
      setNotice('Subtitle segment v'+((segment.version??1)+1)+' saved.');await load();
    } catch(e) {setError(e instanceof Error?e.message:'Subtitle segment update failed');}
    finally {setBusy(false);}
  }
  async function deleteSubtitleSegment(track:SubtitleTrackItem,segment:SubtitleSegmentItem) {
    setBusy(true);setError('');
    try {
      await call('/projects/'+projectId+'/subtitles/'+track.id+'/segments/'+segment.id,{method:'DELETE'});
      setSelectedSubtitleSegments(current=>current.filter(id=>id!==segment.id));
      setNotice('Subtitle segment deleted; its revision history is retained.');await load();
    } catch(e) {setError(e instanceof Error?e.message:'Subtitle segment delete failed');}
    finally {setBusy(false);}
  }
  async function splitSubtitleSegment(track:SubtitleTrackItem,segment:SubtitleSegmentItem) {
    const splitAt=Math.floor((segment.start_ms+segment.end_ms)/2);
    setBusy(true);setError('');
    try {
      await call('/projects/'+projectId+'/subtitles/'+track.id+'/segments/'+segment.id+'/split',{
        method:'POST',body:JSON.stringify({split_at_ms:splitAt}),
      });
      setNotice('Subtitle segment split at '+(splitAt/1000).toFixed(2)+'s.');await load();
    } catch(e) {setError(e instanceof Error?e.message:'Subtitle segment split failed');}
    finally {setBusy(false);}
  }
  async function mergeSelectedSubtitleSegments(track:SubtitleTrackItem) {
    if(selectedSubtitleSegments.length<2)return;
    setBusy(true);setError('');
    try {
      await call('/projects/'+projectId+'/subtitles/'+track.id+'/segments/merge',{
        method:'POST',body:JSON.stringify({segment_ids:selectedSubtitleSegments,separator:' '}),
      });
      setSelectedSubtitleSegments([]);setNotice('Selected subtitle segments merged.');await load();
    } catch(e) {setError(e instanceof Error?e.message:'Subtitle segment merge failed');}
    finally {setBusy(false);}
  }
  async function reorderSubtitleSegment(track:SubtitleTrackItem,segment:SubtitleSegmentItem,direction:-1|1) {
    const ids=track.segments.map(item=>item.id);const index=ids.indexOf(segment.id);const target=index+direction;
    if(index<0||target<0||target>=ids.length)return;
    [ids[index],ids[target]]=[ids[target],ids[index]];
    setBusy(true);setError('');
    try {
      await call('/projects/'+projectId+'/subtitles/'+track.id+'/segments/reorder',{
        method:'PUT',body:JSON.stringify({segment_ids:ids}),
      });
      setNotice('Subtitle segment order updated.');await load();
    } catch(e) {setError(e instanceof Error?e.message:'Subtitle segment reorder failed');}
    finally {setBusy(false);}
  }

  async function importSubtitleTrack(event:React.FormEvent) {
    event.preventDefault();setBusy(true);setError('');
    try{
      const result=await call<{data:{id:string;segment_count:number}}>('/projects/'+projectId+'/subtitles/import',{
        method:'POST',body:JSON.stringify({language:project?.default_language||'id-ID',format:subtitleFormat,content:subtitleImport,style_config:{position:'bottom'}}),
      });
      setNotice('Subtitle track imported · '+result.data.segment_count+' segments');setSubtitleImport('');await load();
    }catch(e){setError(e instanceof Error?e.message:'Subtitle import failed');}
    finally{setBusy(false);}
  }
  async function exportSubtitleTrack(track:SubtitleTrackItem) {
    try{
      const result=await call<{data:{format:string;content:string}}>('/projects/'+projectId+'/subtitles/'+track.id+'/export');
      const blob=new Blob([result.data.content],{type:track.format==='srt'?'application/x-subrip':'text/vtt'});
      const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='graphytion-subtitles.'+(track.format==='srt'?'srt':'vtt');a.click();URL.revokeObjectURL(url);
    }catch(e){setError(e instanceof Error?e.message:'Subtitle export failed');}
  }
  function attachSubtitleTrack(track:SubtitleTrackItem) {
    if(!previewSnapshot){setError('Open a Remotion preview before attaching subtitles to the timeline.');return;}
    let subtitleTrack=previewSnapshot.tracks.find(t=>t.kind==='subtitle'&&!t.locked);
    let tracks=previewSnapshot.tracks;
    if(!subtitleTrack){subtitleTrack={id:crypto.randomUUID(),kind:'subtitle',name:'Subtitles · '+track.language,zIndex:Math.max(0,...tracks.map(t=>t.zIndex))+10,visible:true,locked:false,muted:false,volume:1};tracks=[...tracks,subtitleTrack];}
    const clips=track.segments.map(seg=>({id:crypto.randomUUID(),trackId:subtitleTrack!.id,startFrame:Math.round(seg.start_ms*previewSnapshot.fps/1000),durationFrames:Math.max(1,Math.round((seg.end_ms-seg.start_ms)*previewSnapshot.fps/1000)),trimStartFrames:0,playbackRate:1,componentKey:'text.subtitle.v1',componentVersion:'1.0.0',props:{text:seg.text,color:'#ffffff',background:'rgba(0,0,0,.65)',fontSize:32,position:'bottom',align:'center'}}));
    const durationFrames=Math.max(previewSnapshot.durationFrames,...clips.map(c=>c.startFrame+c.durationFrames));
    setPreviewSnapshot({...previewSnapshot,tracks,clips:[...previewSnapshot.clips,...clips],durationFrames});setTimelineDirty(true);
    setNotice('Subtitle segments attached to Remotion timeline.');
  }

  async function loadTimelineHistory() {
    try{const result=await call<{data:TimelineHistoryItem[]}>('/projects/'+projectId+'/timelines');setTimelineHistory(result.data);}
    catch(e){setError(e instanceof Error?e.message:'Timeline history could not be loaded');}
  }
  async function restoreTimelineVersion(item:TimelineHistoryItem) {
    try{
      const result=await call<{data:{snapshot:CompositionSnapshot;resolved_assets:ResolvedCompositionAssets;version:number}}>('/projects/'+projectId+'/timelines/'+item.id);
      setPreviewSnapshot(result.data.snapshot);setPreviewResolvedAssets(result.data.resolved_assets||{});
      setTimelineVersion(timelineHistory[0]?.version??result.data.version);setTimelineDirty(true);
      setNotice('Timeline v'+item.version+' restored into editor. Save creates a new immutable version.');
    }catch(e){setError(e instanceof Error?e.message:'Timeline version restore failed');}
  }

  async function saveTimelineVersion() {
    if(!previewSnapshot||timelineSaving)return;
    const snapshotToSave=previewSnapshot;
    setTimelineSaving(true);setError('');
    try{
      const result=await call<{data:{timeline_id:string;version:number;compiled_hash:string}}>('/projects/'+projectId+'/timeline',{
        method:'PUT',body:JSON.stringify({snapshot:snapshotToSave,expected_version:timelineVersion}),
      });
      setTimelineVersion(result.data.version);
      if(JSON.stringify(snapshotToSave)===JSON.stringify(previewSnapshot))setTimelineDirty(false);
      setNotice('Timeline version v'+result.data.version+' tersimpan · '+result.data.compiled_hash.slice(0,12)); await loadTimelineHistory();
    }catch(e){setError(e instanceof Error?e.message:'Timeline save failed');}
    finally{setTimelineSaving(false);}
  }

  async function renderCurrentTimeline() {
    if(!previewSnapshot)return;
    setBusy(true);setError('');setNotice('');
    try{
      const result=await call<{data:{render_job_id:string;status:string}}>('/projects/'+projectId+'/renders',{
        method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()},
        body:JSON.stringify({snapshot:previewSnapshot}),
      });
      setNotice('Current timeline render queued · '+result.data.render_job_id);
      await load();
    }catch(e){setError(e instanceof Error?e.message:'Timeline render submission failed');}
    finally{setBusy(false);}
  }

  useEffect(()=>{
    if(!previewSnapshot||!timelineDirty||timelineSaving)return;
    const handle=window.setTimeout(()=>{void saveTimelineVersion();},1500);
    return ()=>window.clearTimeout(handle);
  },[previewSnapshot,timelineDirty,timelineSaving,timelineVersion]);

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

  async function cancelRun(id: string) {
    setBusy(true); setError('');
    try { await call('/creative-runs/' + id + '/cancel', { method: 'POST' }); setNotice('Queued creative run cancelled.'); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Creative run cancellation failed'); }
    finally { setBusy(false); }
  }

  async function cancelRender(id: string) {
    setBusy(true); setError('');
    try { await call('/renders/' + id + '/cancel', { method: 'POST' }); setNotice('Queued render cancelled.'); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : 'Render cancellation failed'); }
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
      <div style={{marginTop:16,display:'grid',gap:8}}>{boards.map(b=><article key={b.id} style={{padding:12,border:'1px solid #edf0f5',borderRadius:10}}><div style={{display:'flex',justifyContent:'space-between',gap:8,alignItems:'center',flexWrap:'wrap'}}><strong>Storyboard v{b.version} · {b.scenes.length} scene</strong><div style={{display:'flex',gap:7}}>{b.status==='draft'&&<button type="button" disabled={busy} onClick={()=>void approveStoryboard(b.id)} style={button}>Approve</button>}{b.status==='approved'&&<><button type="button" disabled={busy} onClick={()=>void previewStoryboard(b.id)} style={{...button,background:'#edf3f9',color:'#173f72'}}>Preview Remotion</button><button type="button" disabled={busy} onClick={()=>void renderStoryboard(b.id)} style={{...button,background:'#0d6b54'}}>Render MP4</button></>}</div></div><p style={{fontSize:13,color:'#68788e',margin:'4px 0'}}>Script: {scripts.find(s=>s.id===b.script_id)?.title||b.script_id} · {b.status}</p>{b.scenes.map(sc=><div key={sc.id} style={{padding:'8px 0',borderTop:'1px solid #edf0f5',display:'flex',justifyContent:'space-between',alignItems:'center',gap:8,flexWrap:'wrap'}}><div><strong>{sc.scene_index+1}. {sc.title}</strong><p style={{fontSize:12,color:'#68788e',margin:'3px 0'}}>{sc.purpose||sc.narration_text||'No scene description'} · {Math.round(sc.duration_ms/1000)}s</p></div><button type="button" disabled={busy||b.status==='superseded'} onClick={()=>void regenerateScene(sc.id)} style={{...button,background:'#edf3f9',color:'#173f72'}}>Regenerate scene</button></div>)}</article>)}</div>
    </section>
    {previewSnapshot && <section style={panel}>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',gap:10,flexWrap:'wrap',marginBottom:12}}>
        <div><h2 style={{margin:'0 0 4px'}}>Remotion Player Preview</h2><p style={{fontSize:12,color:'#68788e',margin:0}}>Storyboard {previewStoryboardId} · {previewSnapshot.width}×{previewSnapshot.height} · {previewSnapshot.fps} FPS · {Math.ceil(previewSnapshot.durationFrames/previewSnapshot.fps)}s · {(previewSnapshot.contentHash??'pending hash').slice(0,12)}</p></div>
        <button type="button" onClick={()=>{setPreviewSnapshot(null);setPreviewResolvedAssets({});setPreviewStoryboardId('');setTimelineDirty(false);}} style={{...button,background:'#edf3f9',color:'#173f72'}}>Close preview</button>
      </div>
      <TimelineEditor snapshot={previewSnapshot} resolvedAssets={previewResolvedAssets} assets={assets} savedVersion={timelineVersion} saving={timelineSaving} onChange={next=>{setPreviewSnapshot(next);setTimelineDirty(true);}} onSave={()=>void saveTimelineVersion()}/>
      <div style={{display:'flex',gap:8,flexWrap:'wrap',marginTop:12}}><button type="button" disabled={busy||timelineSaving} onClick={()=>void renderCurrentTimeline()} style={{...button,background:'#0d6b54'}}>Render current timeline</button><button type="button" disabled={timelineSaving||!timelineDirty} onClick={()=>void saveTimelineVersion()} style={{...button,background:'#edf3f9',color:'#173f72'}}>Save timeline now</button></div>
      <section style={{border:'1px solid #edf0f5',borderRadius:10,padding:10,marginTop:10}}>
        <strong style={{fontSize:12}}>Timeline version history</strong>
        {timelineHistory.map(item=><div key={item.id} style={{display:'flex',justifyContent:'space-between',alignItems:'center',gap:8,flexWrap:'wrap',padding:'7px 0',borderTop:'1px solid #edf0f5'}}>
          <div><strong>v{item.version} · {item.width}×{item.height} · {item.fps} FPS</strong><div style={{fontSize:11,color:'#68788e'}}>{new Date(item.created_at).toLocaleString()} · {item.compiled_hash.slice(0,12)}</div></div>
          <button type="button" onClick={()=>void restoreTimelineVersion(item)} style={{...button,background:'#edf3f9',color:'#173f72'}}>Restore as draft</button>
        </div>)}
        {timelineHistory.length===0&&<p style={{fontSize:11,color:'#68788e'}}>Versions appear after the first autosave.</p>}
      </section>
    </section>}
    <section style={panel}>
      <h2 style={{marginTop:0}}>04 · Creative runs</h2>
      {runs.map(run=><div key={run.id} style={{display:'flex',justifyContent:'space-between',alignItems:'center',gap:8,padding:'8px 0',borderTop:'1px solid #edf0f5',flexWrap:'wrap'}}><div><strong>{run.current_stage || 'Creative pipeline'} · {run.status}</strong><p style={{fontSize:12,color:'#68788e',margin:'3px 0'}}>Progress {run.progress_percent ?? 0}% · {run.error_code || run.id}</p></div>{['queued','planning','scripting','storyboarding'].includes(run.status)&&<button type="button" disabled={busy} onClick={()=>void cancelRun(run.id)} style={{...button,background:'#fff1f0',color:'#b42318'}}>Cancel</button>}</div>)}
      {runs.length===0&&<p style={{color:'#68788e'}}>Belum ada creative run.</p>}
    </section>
    <section style={panel}>
      <h2 style={{marginTop:0}}>05 · Render jobs</h2>
      {renders.map(render=><div key={render.id} style={{display:'flex',justifyContent:'space-between',alignItems:'center',gap:10,padding:'8px 0',borderTop:'1px solid #edf0f5',flexWrap:'wrap'}}><div><strong>{render.status}</strong><p style={{fontSize:12,color:'#68788e',margin:'3px 0'}}>Progress {render.progress_percent}% · {render.error_code || render.id}</p></div><div style={{display:'flex',gap:7}}>{render.status==='completed'&&<button type="button" onClick={()=>void downloadRender(render.id)} style={button}>Download MP4</button>}{['queued','rendering'].includes(render.status)&&<button type="button" disabled={busy} onClick={()=>void cancelRender(render.id)} style={{...button,background:'#fff1f0',color:'#b42318'}}>Cancel</button>}</div></div>)}
      {renders.length===0&&<p style={{color:'#68788e'}}>Belum ada render job.</p>}
    </section>
    <section style={panel}>
      <h2 style={{marginTop:0}}>06 · Project assets</h2>
      <form onSubmit={uploadAsset} style={{display:'flex',gap:9,alignItems:'center',flexWrap:'wrap',marginBottom:12}}>
        <input type="file" aria-label="Upload project asset" accept="image/png,image/jpeg,image/webp,image/svg+xml,video/mp4,audio/mpeg,audio/wav,font/woff2,font/woff,font/ttf,font/otf,application/pdf" onChange={event=>setAssetFile(event.target.files?.[0]||null)} style={{...field,maxWidth:380}}/>
        <button disabled={busy||!assetFile} style={button}>Upload asset</button>
      </form>
      <p style={{fontSize:12,color:'#68788e'}}>Private Supabase Storage · PNG, JPEG, WebP, sanitized SVG, MP4, MP3, WAV, WOFF2/WOFF/TTF/OTF, PDF · max 50 MB</p>
      {assets.map(asset=><div key={asset.id} style={{display:'flex',justifyContent:'space-between',alignItems:'center',gap:10,padding:'8px 0',borderTop:'1px solid #edf0f5',flexWrap:'wrap'}}><div><strong>{asset.file_name}</strong><p style={{fontSize:12,color:'#68788e',margin:'3px 0'}}>{asset.content_type} · {(asset.size_bytes/1024/1024).toFixed(2)} MB · {asset.sha256.slice(0,12)}</p></div><div style={{display:'flex',gap:7}}><button type="button" onClick={()=>void downloadAsset(asset)} style={button}>Download</button><button type="button" disabled={busy} onClick={()=>void deleteAsset(asset)} style={{...button,background:'#fff1f0',color:'#b42318'}}>Delete</button></div></div>)}
      {assets.length===0&&<p style={{color:'#68788e'}}>No project assets uploaded.</p>}
    </section>
    <section style={panel}>
      <h2 style={{marginTop:0}}>07 · Voice-over & TTS</h2>
      <p style={{fontSize:13,color:'#68788e'}}>Provider-independent TTS lifecycle. Jika credentials belum tersedia, request akan tersimpan sebagai provider_unavailable dan tidak menghasilkan audio palsu.</p>
      <form onSubmit={generateVoiceover} style={{display:'grid',gap:8}}>
        <textarea aria-label="Voice-over text" rows={4} required value={voiceText} onChange={e=>setVoiceText(e.target.value)} placeholder="Masukkan narasi voice-over…" style={field}/>
        <select aria-label="Regenerate subtitle segment" value={selectedVoiceSubtitleSegmentId} onChange={event=>{
          const id=event.target.value;setSelectedVoiceSubtitleSegmentId(id);
          const selected=subtitleTracks.flatMap(track=>track.segments).find(segment=>segment.id===id);
          if(selected)setVoiceText(selected.text);
        }} style={field}>
          <option value="">Generate whole voice-over (no subtitle segment link)</option>
          {subtitleTracks.flatMap(track=>track.segments.map(segment=><option key={segment.id} value={segment.id}>{track.language} · #{segment.segment_index+1} · {segment.text.slice(0,70)}</option>))}
        </select>
        <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(160px,1fr))',gap:8}}>
          <select aria-label="TTS provider" value={voiceProvider} onChange={e=>{const provider=e.target.value as 'gemini'|'openai';setVoiceProvider(provider);setVoiceModel(provider==='gemini'?'gemini-3.8-flash-lite-tts':'tts-1');setVoiceKey(provider==='gemini'?'Kore':'alloy');}} style={field}><option value="gemini">Google Gemini TTS</option><option value="openai">OpenAI TTS</option></select>
          <select aria-label="TTS model" value={voiceModel} onChange={e=>setVoiceModel(e.target.value)} style={field}>{voiceProvider==='gemini'?<option value="gemini-3.8-flash-lite-tts">Gemini Flash Lite TTS</option>:<><option value="tts-1">TTS Standard</option><option value="tts-1-hd">TTS HD</option><option value="gpt-4o-mini-tts">GPT-4o mini TTS</option></>}</select>
          <select aria-label="TTS voice" value={voiceKey} onChange={e=>setVoiceKey(e.target.value)} style={field}>{(voiceProvider==='gemini'?['Kore','Puck','Charon','Fenrir','Aoede','Leda','Orus','Zephyr','Callirrhoe','Autonoe','Enceladus','Iapetus','Umbriel','Algieba','Despina','Erinome','Algenib','Rasalgethi','Laomedeia','Achernar','Alnilam','Schedar','Gacrux','Pulcherrima','Achird','Zubenelgenubi','Vindemiatrix','Sadachbia','Sadaltager','Sulafat']:['alloy','ash','coral','echo','fable','onyx','nova','sage','shimmer','verse']).map(v=><option key={v}>{v}</option>)}</select>
          <button disabled={busy||!voiceText.trim()} style={button}>Generate voice-over</button>
        </div>
      </form>
      {voiceovers.map(item=><div key={item.id} style={{display:'flex',justifyContent:'space-between',gap:8,alignItems:'center',flexWrap:'wrap',padding:'8px 0',borderTop:'1px solid #edf0f5'}}>
        <div><strong>{item.voice_key} · {item.model_key} · {item.status}</strong><div style={{fontSize:12,color:'#68788e'}}>Language {item.language} · attempt {item.attempt_count} · {item.error_code||item.asset_id||item.id}</div></div>
        {item.status==='completed'&&item.asset_id&&<button type="button" onClick={()=>void load()} style={{...button,background:'#edf3f9',color:'#173f72'}}>Refresh assets</button>}
        {(item.status==='provider_unavailable'||item.status==='failed')&&<button type="button" disabled={busy} onClick={()=>void retryVoiceover(item)} style={button}>Retry after provider setup</button>}
      </div>)}
      {voiceovers.length===0&&<p style={{fontSize:12,color:'#68788e'}}>Belum ada voice-over job.</p>}
    </section>
    <section style={panel}>
      <h2 style={{marginTop:0}}>08 · Subtitle tracks</h2>
      <form onSubmit={importSubtitleTrack} style={{display:'grid',gap:8}}>
        <div style={{display:'flex',gap:8,flexWrap:'wrap',alignItems:'center'}}><select aria-label="Subtitle format" value={subtitleFormat} onChange={e=>setSubtitleFormat(e.target.value as 'srt'|'webvtt')} style={{...field,maxWidth:160}}><option value="srt">SRT</option><option value="webvtt">WebVTT</option></select><button disabled={busy||!subtitleImport.trim()} style={button}>Import subtitle file content</button></div>
        <textarea aria-label="Subtitle import content" rows={6} value={subtitleImport} onChange={e=>setSubtitleImport(e.target.value)} placeholder="Paste SRT / WebVTT content…" style={{...field,fontFamily:'monospace',fontSize:12}}/>
      </form>
      {subtitleTracks.map(track=><article key={track.id} style={{padding:10,border:'1px solid #edf0f5',borderRadius:9,marginTop:10}}>
        <div style={{display:'flex',justifyContent:'space-between',gap:8,alignItems:'center',flexWrap:'wrap'}}><div><strong>{track.language} · {track.format.toUpperCase()} · v{track.version}</strong><div style={{fontSize:12,color:'#68788e'}}>{track.segments.length} segments</div></div><div style={{display:'flex',gap:6}}><button type="button" onClick={()=>void exportSubtitleTrack(track)} style={{...button,background:'#edf3f9',color:'#173f72'}}>Export</button><button type="button" disabled={!previewSnapshot} onClick={()=>attachSubtitleTrack(track)} style={button}>Attach to timeline</button></div></div>
        <div style={{display:'flex',gap:7,marginTop:10}}>
          <input aria-label="New subtitle segment text" value={newSubtitleText} onChange={event=>setNewSubtitleText(event.target.value)} placeholder="New subtitle segment text…" style={field}/>
          <button type="button" disabled={busy||!newSubtitleText.trim()} onClick={()=>void createSubtitleSegment(track)} style={button}>Add segment</button>
        </div>
        <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',gap:8,marginTop:10}}>
          <span style={{fontSize:11,color:'#68788e'}}>Segment editor · stable IDs · revision history</span>
          <button type="button" disabled={busy||selectedSubtitleSegments.length<2} onClick={()=>void mergeSelectedSubtitleSegments(track)} style={{...button,background:'#edf3f9',color:'#173f72'}}>Merge selected ({selectedSubtitleSegments.length})</button>
        </div>
        {track.segments.map(segment=>{
          const draft=subtitleDrafts[segment.id]??{text:segment.text,start_ms:segment.start_ms,end_ms:segment.end_ms};
          return <div key={segment.id} style={{padding:'10px 0',borderTop:'1px solid #edf0f5',display:'grid',gap:7}}>
            <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',gap:8,flexWrap:'wrap'}}>
              <label style={{fontSize:11,color:'#68788e',display:'flex',alignItems:'center',gap:6}}>
                <input type="checkbox" checked={selectedSubtitleSegments.includes(segment.id)} onChange={event=>setSelectedSubtitleSegments(current=>event.target.checked?[...current,segment.id]:current.filter(id=>id!==segment.id))}/>
                #{segment.segment_index+1} · v{segment.version??1} · {segment.id.slice(0,8)}
              </label>
              <div style={{display:'flex',gap:5,flexWrap:'wrap'}}>
                <button type="button" disabled={busy} onClick={()=>void reorderSubtitleSegment(track,segment,-1)} style={{...button,padding:'6px 9px',background:'#edf3f9',color:'#173f72'}}>↑</button>
                <button type="button" disabled={busy} onClick={()=>void reorderSubtitleSegment(track,segment,1)} style={{...button,padding:'6px 9px',background:'#edf3f9',color:'#173f72'}}>↓</button>
                <button type="button" disabled={busy} onClick={()=>void splitSubtitleSegment(track,segment)} style={{...button,padding:'6px 9px'}}>Split</button>
                <button type="button" disabled={busy} onClick={()=>void saveSubtitleSegment(track,segment)} style={{...button,padding:'6px 9px'}}>Save</button>
                <button type="button" disabled={busy} onClick={()=>void deleteSubtitleSegment(track,segment)} style={{...button,padding:'6px 9px',background:'#9f2d35'}}>Delete</button>
              </div>
            </div>
            <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:6}}>
              <label style={{fontSize:11,color:'#68788e'}}>Start (ms)<input type="number" min={0} value={draft.start_ms} onChange={event=>updateSubtitleDraft(segment,{start_ms:Number(event.target.value)})} style={field}/></label>
              <label style={{fontSize:11,color:'#68788e'}}>End (ms)<input type="number" min={1} value={draft.end_ms} onChange={event=>updateSubtitleDraft(segment,{end_ms:Number(event.target.value)})} style={field}/></label>
            </div>
            <textarea aria-label={'Subtitle text '+segment.segment_index} rows={2} value={draft.text} onChange={event=>updateSubtitleDraft(segment,{text:event.target.value})} style={{...field,fontSize:12}}/>
            <div style={{fontSize:10,color:'#68788e'}}>Word alignment: {segment.word_timings?.length??0} words · Audio asset: {segment.audio_asset_id?'linked':'not linked'}</div>
          </div>;
        })}
      </article>)}
      {subtitleTracks.length===0&&<p style={{fontSize:12,color:'#68788e'}}>Belum ada subtitle track.</p>}
    </section>
    <p style={{fontSize:12,color:'#68788e'}}>AI generation berjalan melalui FastAPI Model Router dengan structured output, prompt version, dan persisted run lifecycle. Jika provider adapter belum diregistrasikan pada runtime, API mengembalikan status unavailable dan tidak membuat hasil AI palsu.</p>
  </main>;
}
