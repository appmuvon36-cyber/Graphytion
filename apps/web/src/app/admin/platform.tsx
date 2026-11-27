'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiClientError, createApiClient } from '@graphytion/api-client';

type Page<T> = { data: T[]; page: { number: number; size: number; total?: number; has_more?: boolean } };
type User = { id: string; email?: string; email_confirmed_at?: string | null; last_sign_in_at?: string | null; created_at?: string; banned_until?: string | null; profile?: { display_name?: string | null } };
type Workspace = { id: string; name: string; slug: string; active_members: number; projects: number; owner_user_id: string };
type Project = { id: string; name: string; workspace_name: string; status: string; production_mode: string };
type Audit = { id: string; action: string; actor_user_id: string; resource_type: string; resource_id: string; created_at: string };
type Member = { id: string; user_id: string; display_name?: string | null; role: string; status: string };
type Invitation = { id: string; workspace_name: string; email: string; role: string; delivery_status: string; expires_at: string; accepted_at?: string | null; cancelled_at?: string | null };
type PlatformAdminRecord = { user_id: string; role: string; status: string; granted_at: string; reason?: string | null };
type Overview = { users: number; workspaces: number; active_memberships: number; projects: number; audit_events_24h: number; active_creative_runs: number; active_render_jobs: number; input_tokens_24h: number; output_tokens_24h: number };
type LlmStatus = { available_providers: string[]; configured_model: string; openai_credential_configured: boolean; generation_ready: boolean };
type RenderProfile={id:string;profile_key:string;name:string;version:number;width:number;height:number;fps:number;container:string;video_codec:string;video_crf:number;audio_codec:string;render_concurrency:number;priority:number;is_default:boolean;is_archived:boolean};
type RenderSettings={max_concurrent_jobs:number;lease_seconds:number;max_attempts:number;max_output_bytes:number;updated_at?:string|null};
type MotionControl={component_key:string;component_version:string;category:string;enabled:boolean;reason?:string|null};
type AdminRenderJob={id:string;project_name:string;workspace_name:string;status:string;progress_percent:number;worker_id?:string|null;lease_expires_at?:string|null;render_profile?:string|null;attempt_count:number;latest_attempt_status?:string|null};
type AdminMediaJob={id:string;project_name:string;workspace_name:string;status:string;provider_key:string;model_key:string;voice_key:string;worker_id?:string|null;lease_expires_at?:string|null;attempt_count:number;max_attempts:number;error_code?:string|null;asset_id?:string|null};
type ModelPrice = { id:string; provider_key:string; model_key:string; input_microusd_per_million:number; output_microusd_per_million:number; effective_at:string; is_active:boolean; notes?:string|null };
type UsageSummary = { period_days:number; totals:{input_tokens:number;output_tokens:number;priced_cost_microusd:number;priced_events:number;unpriced_events:number}; by_provider_model:Array<{provider_key:string;model_key:string;input_tokens:number;output_tokens:number;cost_microusd:number;events:number}> };
type WorkerStatus={worker_id:string;worker_type:'media'|'render';hostname:string;version?:string|null;status:string;runtime_status:'online'|'stale';last_seen_at:string;metadata?:Record<string,unknown>};

const apiBase = typeof window !== 'undefined' ? window.location.origin + '/api' : 'http://localhost:3001/api';
const input: React.CSSProperties = { width: '100%', padding: 10, border: '1px solid #dce3ed', borderRadius: 8 };
const button: React.CSSProperties = { border: 0, borderRadius: 8, padding: '9px 12px', background: '#173f72', color: '#fff', fontWeight: 700, cursor: 'pointer' };
const panel: React.CSSProperties = { background: '#fff', border: '1px solid #e5eaf1', borderRadius: 13, padding: 18, marginBottom: 14 };

export default function PlatformAdmin() {
  const api = useMemo(() => createApiClient({ baseUrl: apiBase }), []);
  const [authenticated, setAuthenticated] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [overview, setOverview] = useState<Overview | null>(null);
  const [llmStatus, setLlmStatus] = useState<LlmStatus | null>(null);
  const [modelPrices,setModelPrices]=useState<ModelPrice[]>([]);
  const [usageSummary,setUsageSummary]=useState<UsageSummary|null>(null);
  const [pricingError,setPricingError]=useState('');
  const [priceDraft,setPriceDraft]=useState({provider_key:'openai',model_key:'gpt-4.1-mini',input_microusd_per_million:0,output_microusd_per_million:0,notes:''});
  const [renderProfiles,setRenderProfiles]=useState<RenderProfile[]>([]);
  const [renderSettings,setRenderSettings]=useState<RenderSettings>({max_concurrent_jobs:2,lease_seconds:300,max_attempts:3,max_output_bytes:536870912});
  const [motionComponents,setMotionComponents]=useState<MotionControl[]>([]);
  const [adminRenderJobs,setAdminRenderJobs]=useState<AdminRenderJob[]>([]);
  const [adminMediaJobs,setAdminMediaJobs]=useState<AdminMediaJob[]>([]);
  const [workers,setWorkers]=useState<WorkerStatus[]>([]);
  const [profileDraft,setProfileDraft]=useState({profile_key:'custom-1080p',name:'Custom 1080p',width:1920,height:1080,fps:30,container:'mp4',video_codec:'h264',video_crf:20,audio_codec:'aac',render_concurrency:2,priority:20,is_default:false});
  const [editingProfileId,setEditingProfileId]=useState<string|null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [audit, setAudit] = useState<Audit[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState('');
  const [members, setMembers] = useState<Member[]>([]);
  const [quotaLimit,setQuotaLimit]=useState('');
  const [quotaStart,setQuotaStart]=useState('');
  const [quotaEnd,setQuotaEnd]=useState('');
  const [quotaStatus,setQuotaStatus]=useState<'active'|'paused'>('active');
  const [quotaSummary,setQuotaSummary]=useState<{consumed_microusd:number;reserved_microusd:number;available_microusd:number}|null>(null);
  const [voiceoverRate,setVoiceoverRate]=useState('');
  const [renderRate,setRenderRate]=useState('');
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [platformAdmins, setPlatformAdmins] = useState<PlatformAdminRecord[]>([]);
  const [newAdminUserId, setNewAdminUserId] = useState('');
  const [newAdminRole, setNewAdminRole] = useState('operations_admin');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [denied, setDenied] = useState(false);

  const request = useCallback(async <T,>(path: string, init?: RequestInit) => {
    try { return await api.request<T>(path, init); }
    catch (cause) {
      if (cause instanceof ApiClientError && cause.status === 401) setAuthenticated(false);
      if (cause instanceof ApiClientError && cause.status === 403) setDenied(true);
      throw cause;
    }
  }, [api]);

  const load = useCallback(async () => {
    setBusy(true); setError('');
    try {
      const [o, u, w, p, a, i, pa, llm, rp, rs, mc, rj, mj, wk] = await Promise.all([
        request<{data: Overview}>('/admin/overview'),
        request<Page<User>>('/admin/users?page=' + page + '&per_page=25&q=' + encodeURIComponent(query)),
        request<Page<Workspace>>('/admin/workspaces?page=1&per_page=50&q=' + encodeURIComponent(query)),
        request<Page<Project>>('/admin/projects?page=1&per_page=50&q=' + encodeURIComponent(query)),
        request<Page<Audit>>('/admin/audit-logs?page=1&per_page=30'),
        request<Page<Invitation>>('/admin/invitations?page=1&per_page=50'),
        request<{data: PlatformAdminRecord[]}>('/admin/platform-admins'),
        request<{data: LlmStatus}>('/admin/llm/providers'),
        request<{data:RenderProfile[]}>('/admin/render-profiles'),
        request<{data:RenderSettings}>('/admin/render-settings'),
        request<{data:MotionControl[]}>('/admin/motion-components'),
        request<Page<AdminRenderJob>>('/admin/render-jobs?page=1&per_page=50'),
        request<Page<AdminMediaJob>>('/admin/media-jobs?page=1&per_page=50'),
        request<{data:WorkerStatus[]}>('/admin/workers'),
      ]);
      setOverview(o.data); setUsers(u.data); setWorkspaces(w.data); setProjects(p.data); setAudit(a.data); setInvitations(i.data); setPlatformAdmins(pa.data); setLlmStatus(llm.data); setRenderProfiles(rp.data); setRenderSettings(rs.data); setMotionComponents(mc.data); setAdminRenderJobs(rj.data); setAdminMediaJobs(mj.data); setWorkers(wk.data);
      setDenied(false);
      const [pricesResult, usageResult] = await Promise.allSettled([
        request<{data:ModelPrice[]}>('/admin/providers/model-prices'),
        request<{data:UsageSummary}>('/admin/usage?days=30'),
      ]);
      if (pricesResult.status === 'fulfilled') { setModelPrices(pricesResult.value.data); setPricingError(''); }
      else { setModelPrices([]); setPricingError('Usage economics migration is not yet active or the pricing API is unavailable.'); }
      if (usageResult.status === 'fulfilled') setUsageSummary(usageResult.value.data);
      else setUsageSummary(null);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Platform data unavailable'); }
    finally { setBusy(false); }
  }, [page, query, request]);

  useEffect(() => {
    let active = true;
    fetch('/api/csrf', { credentials: 'include', cache: 'no-store' }).finally(() => {
      api.request<{authenticated: boolean}>('/auth/session')
        .then(result => { if (active) setAuthenticated(result.authenticated); })
        .catch(() => { if (active) setAuthenticated(false); });
    });
    return () => { active = false; };
  }, [api]);
  useEffect(() => { if (authenticated) void load(); }, [authenticated, load]);

  async function login(event: React.FormEvent) {
    event.preventDefault(); setError(''); setDenied(false);
    try {
      const result = await api.request<{authenticated: boolean}>('/auth/login', {
        method: 'POST', body: JSON.stringify({ email, password }),
      });
      if (!result.authenticated) throw new Error('Login belum menghasilkan sesi aktif.');
      setAuthenticated(true);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Login gagal'); }
  }

  async function loadMembers(workspaceId: string) {
    setSelectedWorkspace(workspaceId); setMembers([]); setError('');
    try {
      const result = await request<{data: Member[]}>('/admin/workspaces/' + workspaceId + '/members');
      setMembers(result.data);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Gagal memuat membership'); }
  }

  async function loadQuota(workspaceId:string) {
    setSelectedWorkspace(workspaceId); setError('');
    try {
      const result=await request<{data:{quota_limit_microusd:number;period_start:string;period_end:string;status:'active'|'paused';consumed_microusd:number;reserved_microusd:number;available_microusd:number}}>('/admin/workspaces/'+workspaceId+'/quota');
      setQuotaLimit(String(result.data.quota_limit_microusd));
      setQuotaStart(new Date(result.data.period_start).toISOString().slice(0,16));
      setQuotaEnd(new Date(result.data.period_end).toISOString().slice(0,16));
      setQuotaStatus(result.data.status);
      setQuotaSummary({consumed_microusd:result.data.consumed_microusd,reserved_microusd:result.data.reserved_microusd,available_microusd:result.data.available_microusd});
    } catch (cause) { const start=new Date(); const end=new Date(start.getTime()+30*24*60*60*1000); setQuotaLimit(''); setQuotaStart(start.toISOString().slice(0,16)); setQuotaEnd(end.toISOString().slice(0,16)); setQuotaStatus('active'); setQuotaSummary(null); setNotice(cause instanceof Error?cause.message:'Quota account belum dikonfigurasi.'); }
  }

  async function saveQuota(event:React.FormEvent) {
    event.preventDefault(); if(!selectedWorkspace)return;
    setBusy(true);setError('');
    try {
      const result=await request<{data:{consumed_microusd:number;reserved_microusd:number;quota_limit_microusd:number;period_start:string;period_end:string;status:'active'|'paused'}}>('/admin/workspaces/'+selectedWorkspace+'/quota',{
        method:'PUT',body:JSON.stringify({quota_limit_microusd:Number(quotaLimit),period_start:new Date(quotaStart).toISOString(),period_end:new Date(quotaEnd).toISOString(),status:quotaStatus})
      });
      setQuotaSummary({consumed_microusd:result.data.consumed_microusd,reserved_microusd:result.data.reserved_microusd,available_microusd:result.data.quota_limit_microusd-result.data.consumed_microusd-result.data.reserved_microusd});
      setNotice('Workspace quota account saved.');
    } catch(cause){setError(cause instanceof Error?cause.message:'Quota update failed');}
    finally{setBusy(false);}
  }

  async function saveQuotaRate(operation:string,rate:string,unit:string) {
    setBusy(true);setError('');
    try {
      await request('/admin/quota/operation-prices/'+operation,{method:'PUT',body:JSON.stringify({microusd_per_unit:Number(rate),unit_name:unit,notes:'Configured through Graphytion platform admin'})});
      setNotice('Quota operation rate saved: '+operation);
    } catch(cause){setError(cause instanceof Error?cause.message:'Quota operation rate update failed');}
    finally{setBusy(false);}
  }

  async function updateMemberRole(member: Member, role: string) {
    if (!selectedWorkspace) return;
    setBusy(true); setError('');
    try {
      await request('/admin/workspaces/' + selectedWorkspace + '/members/' + member.id, {
        method: 'PATCH', body: JSON.stringify({ role }),
      });
      await loadMembers(selectedWorkspace);
      setNotice('Workspace member role updated.');
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Perubahan role gagal'); }
    finally { setBusy(false); }
  }

  async function grantPlatformAdmin(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(''); setNotice('');
    try {
      await request('/admin/platform-admins', {
        method: 'POST',
        body: JSON.stringify({ user_id: newAdminUserId.trim(), role: newAdminRole, reason: 'Provisioned through platform control plane' }),
      });
      setNewAdminUserId(''); setNotice('Platform administrator role granted.'); await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Grant platform role failed'); }
    finally { setBusy(false); }
  }

  async function revokePlatformAdmin(admin: PlatformAdminRecord) {
    if (!window.confirm('Revoke platform administrator access for ' + admin.user_id + '?')) return;
    setBusy(true); setError('');
    try {
      await request('/admin/platform-admins/' + admin.user_id, { method: 'DELETE' });
      setNotice('Platform administrator access revoked.'); await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Revoke platform role failed'); }
    finally { setBusy(false); }
  }

  async function updateProjectStatus(project: Project, status: 'draft' | 'archived') {
    const reason = window.prompt(status === 'archived' ? 'Reason to archive this project:' : 'Reason to restore this project:');
    if (!reason || reason.trim().length < 3) return;
    setBusy(true); setError('');
    try {
      await request('/admin/projects/' + project.id + '/status', {
        method: 'PATCH', body: JSON.stringify({ status, reason: reason.trim() }),
      });
      setNotice('Project lifecycle updated.');
      await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Project lifecycle update failed'); }
    finally { setBusy(false); }
  }

  async function cancelInvitation(invitation: Invitation) {
    if (!window.confirm('Cancel invitation for ' + invitation.email + '?')) return;
    setBusy(true); setError('');
    try {
      await request('/admin/invitations/' + invitation.id, { method: 'DELETE' });
      setNotice('Invitation cancelled.');
      await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Invitation cancellation failed'); }
    finally { setBusy(false); }
  }

  async function removeMember(member: Member) {
    if (!selectedWorkspace || !window.confirm('Remove member from this workspace?')) return;
    setBusy(true); setError('');
    try {
      await request('/admin/workspaces/' + selectedWorkspace + '/members/' + member.id, { method: 'DELETE' });
      await loadMembers(selectedWorkspace);
      setNotice('Workspace membership removed.');
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Penghapusan membership gagal'); }
    finally { setBusy(false); }
  }

  async function changeStatus(user: User, banned: boolean) {
    const reason = window.prompt(banned ? 'Alasan penangguhan akun:' : 'Alasan pemulihan akun:');
    if (!reason || reason.trim().length < 3) return;
    setBusy(true); setError(''); setNotice('');
    try {
      await request('/admin/users/' + user.id + '/status', {
        method: 'PATCH', body: JSON.stringify({ banned, reason: reason.trim() }),
      });
      setNotice('Status akun diperbarui melalui Supabase Auth Admin API.');
      await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Perubahan status gagal'); }
    finally { setBusy(false); }
  }

  async function saveRenderSettings(event:React.FormEvent) {
    event.preventDefault();setBusy(true);setError('');setNotice('');
    try{
      const result=await request<{data:RenderSettings}>('/admin/render-settings',{method:'PATCH',body:JSON.stringify(renderSettings)});
      setRenderSettings(result.data);setNotice('Global render runtime settings saved and audited.');
    }catch(cause){setError(cause instanceof Error?cause.message:'Global render settings update failed');}
    finally{setBusy(false);}
  }

  async function createRenderProfile(event:React.FormEvent) {
    event.preventDefault();setBusy(true);setError('');setNotice('');
    try{await request(editingProfileId?'/admin/render-profiles/'+editingProfileId:'/admin/render-profiles',{method:editingProfileId?'PATCH':'POST',body:JSON.stringify(profileDraft)});setNotice(editingProfileId?'Render profile version created.':'Render profile created.');setEditingProfileId(null);await load();}
    catch(cause){setError(cause instanceof Error?cause.message:'Render profile creation failed');}
    finally{setBusy(false);}
  }
  function editRenderProfile(profile:RenderProfile) {
    setEditingProfileId(profile.id);
    setProfileDraft({profile_key:profile.profile_key,name:profile.name,width:profile.width,height:profile.height,fps:profile.fps,container:profile.container,video_codec:profile.video_codec,video_crf:profile.video_crf,audio_codec:profile.audio_codec,render_concurrency:profile.render_concurrency,priority:profile.priority,is_default:profile.is_default});
  }
  async function archiveRenderProfile(profile:RenderProfile) {
    if(!window.confirm('Archive '+profile.name+' v'+profile.version+'?'))return;
    setBusy(true);setError('');
    try{await request('/admin/render-profiles/'+profile.id+'/archive',{method:'POST'});setNotice('Render profile archived.');await load();}
    catch(cause){setError(cause instanceof Error?cause.message:'Profile archive failed');}
    finally{setBusy(false);}
  }
  async function retryOperationalJob(kind:'render'|'media', jobId:string) {
    const label=kind==='render'?'render':'voice-over';
    if(!window.confirm('Queue a new attempt for this failed '+label+' job?'))return;
    setBusy(true);setError('');setNotice('');
    try{
      await request('/admin/'+(kind==='render'?'render-jobs':'media-jobs')+'/'+jobId+'/retry',{method:'POST'});
      setNotice('Job queued for retry. PostgreSQL remains the durable queue source.');
      await load();
    }catch(cause){setError(cause instanceof Error?cause.message:'Job retry failed');}
    finally{setBusy(false);}
  }

  async function toggleMotionComponent(item:MotionControl) {
    const reason=window.prompt('Reason for changing component availability',item.enabled?'Temporarily disabled by platform admin':'Re-enabled after review');
    if(!reason)return;
    setBusy(true);setError('');
    try{await request('/admin/motion-components/'+encodeURIComponent(item.component_key),{method:'PATCH',body:JSON.stringify({enabled:!item.enabled,reason})});setNotice('Motion component registry updated.');await load();}
    catch(cause){setError(cause instanceof Error?cause.message:'Component registry update failed');}
    finally{setBusy(false);}
  }


  async function saveModelPrice(event:React.FormEvent) {
    event.preventDefault();setBusy(true);setError('');setNotice('');
    try {
      await request('/admin/providers/model-prices/'+encodeURIComponent(priceDraft.provider_key)+'/'+encodeURIComponent(priceDraft.model_key),{
        method:'PUT',body:JSON.stringify({
          input_microusd_per_million:priceDraft.input_microusd_per_million,
          output_microusd_per_million:priceDraft.output_microusd_per_million,
          notes:priceDraft.notes.trim()||null
        })
      });
      setNotice('Provider model price version saved and audited.');
      await load();
    } catch(cause) { setError(cause instanceof Error?cause.message:'Provider model price update failed'); }
    finally { setBusy(false); }
  }

  async function logout() {
    try { await api.request('/auth/logout', { method: 'POST' }); } catch { /* session may already be expired */ }
    setAuthenticated(false); setOverview(null); setUsers([]); setWorkspaces([]); setProjects([]); setAudit([]);
  }

  if (!authenticated) return <main style={{ maxWidth: 440, margin: '10vh auto', padding: 24 }}>
    <p style={{ fontSize: 11, fontWeight: 800, letterSpacing: '.15em', color: '#47719e' }}>GRAPHYTION · PLATFORM ADMIN</p>
    <h1>Platform control plane</h1><p style={{ color: '#68788e' }}>Masuk dengan identitas Graphytion. Otorisasi platform diverifikasi server-side, terpisah dari role workspace.</p>
    {error && <p role="alert" style={{ color: '#b42318' }}>{error}</p>}
    <form onSubmit={login} style={{ ...panel, display: 'grid', gap: 10 }}>
      <input type="email" required placeholder="Email" value={email} onChange={e => setEmail(e.target.value)} style={input} />
      <input type="password" required placeholder="Password" value={password} onChange={e => setPassword(e.target.value)} style={input} />
      <button style={button}>Masuk</button>
    </form>
  </main>;

  return <main style={{ maxWidth: 1180, margin: '0 auto', padding: '34px 20px' }}>
    <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
      <div><p style={{ fontSize: 11, fontWeight: 800, letterSpacing: '.15em', color: '#47719e' }}>GRAPHYTION · PLATFORM ADMIN</p><h1 style={{ margin: '4px 0' }}>Operational control plane</h1><p style={{ color: '#68788e' }}>Global users, workspaces, projects, and audit events.</p></div>
      <button onClick={() => void logout()} style={{ ...button, background: '#edf3f9', color: '#173f72' }}>Keluar</button>
    </header>
    {error && <p role="alert" style={{ padding: 12, background: '#fff1f0', color: '#b42318', borderRadius: 8 }}>{error}</p>}
    {notice && <p role="status" style={{ padding: 12, background: '#ecfdf3', color: '#176b45', borderRadius: 8 }}>{notice}</p>}
    {denied && <p role="alert" style={{ ...panel, color: '#b42318' }}>Akun ini bukan platform administrator aktif. Role workspace tidak memberikan akses platform.</p>}
    {busy && <p role="status">Memuat data platform…</p>}
    {overview && <>
      <section style={panel}><h2 style={{marginTop:0}}>AI provider configuration</h2>{llmStatus&&<div style={{display:'flex',justifyContent:'space-between',gap:12,flexWrap:'wrap'}}><div><strong>{llmStatus.generation_ready?'Generation provider ready':'Provider configuration required'}</strong><p style={{fontSize:12,color:'#68788e',margin:'4px 0'}}>Model: {llmStatus.configured_model} · Available providers: {llmStatus.available_providers.join(', ')||'none'}</p></div><span style={{fontSize:12,color:llmStatus.generation_ready?'#176b45':'#a15b00'}}>{llmStatus.openai_credential_configured?'OPENAI_API_KEY configured':'OPENAI_API_KEY missing'}</span></div>}</section>

      <section style={panel}>
        <h2>AI usage economics · actual provider usage</h2>
        {pricingError&&<p role="status" style={{fontSize:12,color:'#a15b00'}}>{pricingError}</p>}
        <p style={{fontSize:13,color:'#68788e'}}>Biaya dihitung dari token aktual provider dan price book versi efektif. Event tanpa harga atau metadata token lengkap tetap ditandai unpriced, bukan dianggap gratis.</p>
        {usageSummary&&<div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(150px,1fr))',gap:10,marginBottom:14}}>
          <div><strong>{usageSummary.totals.input_tokens.toLocaleString()}</strong><div style={{fontSize:11,color:'#68788e'}}>Input tokens · 30 hari</div></div>
          <div><strong>{usageSummary.totals.output_tokens.toLocaleString()}</strong><div style={{fontSize:11,color:'#68788e'}}>Output tokens · 30 hari</div></div>
          <div><strong>USD {(usageSummary.totals.priced_cost_microusd/1000000).toFixed(6)}</strong><div style={{fontSize:11,color:'#68788e'}}>Priced provider cost</div></div>
          <div><strong>{usageSummary.totals.unpriced_events}</strong><div style={{fontSize:11,color:'#68788e'}}>Unpriced events · {usageSummary.totals.priced_events} priced</div></div>
        </div>}
        <h3>Versioned provider price book</h3>
        <form onSubmit={saveModelPrice} style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(150px,1fr))',gap:8}}>
          <input aria-label="Provider key" value={priceDraft.provider_key} onChange={e=>setPriceDraft(v=>({...v,provider_key:e.target.value}))} placeholder="openai" style={input}/>
          <input aria-label="Model key" value={priceDraft.model_key} onChange={e=>setPriceDraft(v=>({...v,model_key:e.target.value}))} placeholder="gpt-4.1-mini" style={input}/>
          <label style={{fontSize:11}}>Input micro-USD / 1M tokens<input aria-label="Input micro USD per million tokens" type="number" min={0} step={1} value={priceDraft.input_microusd_per_million} onChange={e=>setPriceDraft(v=>({...v,input_microusd_per_million:Number(e.target.value)}))} style={input}/></label>
          <label style={{fontSize:11}}>Output micro-USD / 1M tokens<input aria-label="Output micro USD per million tokens" type="number" min={0} step={1} value={priceDraft.output_microusd_per_million} onChange={e=>setPriceDraft(v=>({...v,output_microusd_per_million:Number(e.target.value)}))} style={input}/></label>
          <input aria-label="Price notes" value={priceDraft.notes} onChange={e=>setPriceDraft(v=>({...v,notes:e.target.value}))} placeholder="Pricing source / terms" style={input}/>
          <button disabled={busy||!priceDraft.provider_key.trim()||!priceDraft.model_key.trim()} style={button}>Save price version</button>
        </form>
        <p style={{fontSize:11,color:'#68788e'}}>1 USD = 1,000,000 micro-USD. A new rate creates a version; prior usage retains its price snapshot.</p>
        {modelPrices.map(price=><div key={price.id} style={{padding:'7px 0',borderTop:'1px solid #edf0f5',display:'flex',justifyContent:'space-between',gap:8,flexWrap:'wrap'}}>
          <strong>{price.provider_key}/{price.model_key} · {price.is_active?'active':'inactive'}</strong>
          <span style={{fontSize:12,color:'#68788e'}}>In {price.input_microusd_per_million.toLocaleString()} · Out {price.output_microusd_per_million.toLocaleString()} micro-USD/1M · {new Date(price.effective_at).toLocaleString()}</span>
        </div>)}
        {usageSummary?.by_provider_model.map(item=><div key={item.provider_key+'/'+item.model_key} style={{padding:'7px 0',borderTop:'1px solid #edf0f5',display:'flex',justifyContent:'space-between',gap:8,flexWrap:'wrap'}}>
          <span>{item.provider_key}/{item.model_key} · {item.events} events</span>
          <strong>USD {(item.cost_microusd/1000000).toFixed(6)}</strong>
        </div>)}
      </section>
      <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(145px,1fr))', gap: 10, margin: '18px 0' }}>
        {Object.entries({ Users: overview.users, Workspaces: overview.workspaces, 'Active members': overview.active_memberships, Projects: overview.projects, 'Audit 24h': overview.audit_events_24h, 'Active AI runs': overview.active_creative_runs, 'Active renders': overview.active_render_jobs, 'Input tokens 24h': overview.input_tokens_24h, 'Output tokens 24h': overview.output_tokens_24h }).map(([label, value]) =>
          <article key={label} style={panel}><div style={{ fontSize: 12, color: '#68788e' }}>{label}</div><strong style={{ fontSize: 25 }}>{value}</strong></article>)}
      </section>
      <section style={panel}>
        <div style={{ display: 'flex', gap: 10, justifyContent: 'space-between', flexWrap: 'wrap', alignItems: 'center' }}>
          <h2 style={{ margin: 0 }}>User & account management</h2>
          <div style={{ display: 'flex', gap: 8 }}><input aria-label="Search users and workspaces" placeholder="Search email, name, workspace…" value={query} onChange={e => { setPage(1); setQuery(e.target.value); }} style={{ ...input, maxWidth: 280 }} /><button onClick={() => void load()} style={button}>Refresh</button></div>
        </div>
        {users.map(user => <div key={user.id} style={{ display: 'flex', gap: 10, justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid #edf0f5', padding: '12px 0', flexWrap: 'wrap' }}>
          <div><strong>{user.profile?.display_name || user.email || user.id}</strong><div style={{ fontSize: 12, color: '#68788e' }}>{user.email} · {user.email_confirmed_at ? 'verified' : 'unverified'} · {user.banned_until ? 'banned until ' + new Date(user.banned_until).toLocaleString() : 'active'}</div></div>
          <button disabled={busy} onClick={() => void changeStatus(user, !user.banned_until)} style={{ ...button, background: user.banned_until ? '#0d6b54' : '#a83232' }}>{user.banned_until ? 'Unban account' : 'Suspend account'}</button>
        </div>)}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', alignItems: 'center' }}><button disabled={page <= 1 || busy} onClick={() => setPage(value => value - 1)} style={{ ...button, background: '#edf3f9', color: '#173f72' }}>Previous</button><span style={{ fontSize: 12 }}>Page {page}</span><button disabled={users.length < 25 || busy} onClick={() => setPage(value => value + 1)} style={{ ...button, background: '#edf3f9', color: '#173f72' }}>Next</button></div>
      </section>
      <section style={panel}><h2>Platform RBAC & administrator registry</h2><form onSubmit={grantPlatformAdmin} style={{display:'grid',gridTemplateColumns:'2fr 1fr auto',gap:8,marginBottom:12}}><input aria-label="User UUID" placeholder="User profile UUID" value={newAdminUserId} onChange={event=>setNewAdminUserId(event.target.value)} style={input} required/><select aria-label="Platform admin role" value={newAdminRole} onChange={event=>setNewAdminRole(event.target.value)} style={input}><option value="operations_admin">Operations admin</option><option value="support_admin">Support admin</option><option value="super_admin">Super admin</option></select><button disabled={busy} style={button}>Grant role</button></form>{platformAdmins.map(admin=><div key={admin.user_id} style={{display:'flex',justifyContent:'space-between',alignItems:'center',gap:10,padding:'8px 0',borderTop:'1px solid #edf0f5',flexWrap:'wrap'}}><div><strong>{admin.user_id}</strong><div style={{fontSize:12,color:'#68788e'}}>{admin.role} · {admin.status} · {new Date(admin.granted_at).toLocaleString()}</div></div>{admin.status==='active'&&<button disabled={busy} onClick={()=>void revokePlatformAdmin(admin)} style={{...button,background:'#fff1f0',color:'#b42318'}}>Revoke</button>}</div>)}</section>
      <section style={panel}>
        <h2>Global render runtime configuration</h2>
        <p style={{fontSize:13,color:'#68788e'}}>Controls are enforced by FastAPI and PostgreSQL job claims. Profile quality settings remain versioned separately.</p>
        <form onSubmit={saveRenderSettings} style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(160px,1fr))',gap:8}}>
          <label style={{fontSize:12}}>Concurrent render jobs<input aria-label="Maximum concurrent render jobs" type="number" min={1} max={8} value={renderSettings.max_concurrent_jobs} onChange={e=>setRenderSettings(v=>({...v,max_concurrent_jobs:Number(e.target.value)}))} style={input}/></label>
          <label style={{fontSize:12}}>Worker lease seconds<input aria-label="Worker lease seconds" type="number" min={60} max={3600} value={renderSettings.lease_seconds} onChange={e=>setRenderSettings(v=>({...v,lease_seconds:Number(e.target.value)}))} style={input}/></label>
          <label style={{fontSize:12}}>Maximum attempts<input aria-label="Maximum render attempts" type="number" min={1} max={10} value={renderSettings.max_attempts} onChange={e=>setRenderSettings(v=>({...v,max_attempts:Number(e.target.value)}))} style={input}/></label>
          <label style={{fontSize:12}}>Maximum output bytes<input aria-label="Maximum output bytes" type="number" min={1048576} max={536870912} step={1048576} value={renderSettings.max_output_bytes} onChange={e=>setRenderSettings(v=>({...v,max_output_bytes:Number(e.target.value)}))} style={input}/></label>
          <button disabled={busy} style={button}>Save global settings</button>
        </form>
        {renderSettings.updated_at&&<p style={{fontSize:11,color:'#68788e'}}>Last updated {new Date(renderSettings.updated_at).toLocaleString()}</p>}
      </section>
      <section style={panel}>
        <h2>Remotion · Render profiles & quality presets</h2>
        <p style={{fontSize:13,color:'#68788e'}}>New render jobs pin the selected global profile version and immutable composition snapshot.</p>
        <form onSubmit={createRenderProfile} style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(150px,1fr))',gap:8}}>
          <input aria-label="Profile key" value={profileDraft.profile_key} onChange={e=>setProfileDraft(v=>({...v,profile_key:e.target.value}))} placeholder="profile-key" style={input}/>
          <input aria-label="Profile name" value={profileDraft.name} onChange={e=>setProfileDraft(v=>({...v,name:e.target.value}))} placeholder="Profile name" style={input}/>
          <input aria-label="Width" type="number" value={profileDraft.width} onChange={e=>setProfileDraft(v=>({...v,width:Number(e.target.value)}))} style={input}/>
          <input aria-label="Height" type="number" value={profileDraft.height} onChange={e=>setProfileDraft(v=>({...v,height:Number(e.target.value)}))} style={input}/>
          <select aria-label="FPS" value={profileDraft.fps} onChange={e=>setProfileDraft(v=>({...v,fps:Number(e.target.value)}))} style={input}>{[24,25,30,50,60].map(v=><option key={v} value={v}>{v}</option>)}</select>
          <select aria-label="Container" value={profileDraft.container} onChange={e=>setProfileDraft(v=>({...v,container:e.target.value,video_codec:e.target.value==='mp4'?'h264':'vp9',audio_codec:e.target.value==='mp4'?'aac':'opus'}))} style={input}><option value="mp4">MP4</option><option value="webm">WebM</option></select>
          <select aria-label="Video codec" value={profileDraft.video_codec} onChange={e=>setProfileDraft(v=>({...v,video_codec:e.target.value}))} style={input}>{(profileDraft.container==='mp4'?['h264','h265']:['vp8','vp9']).map(v=><option key={v}>{v}</option>)}</select>
          <input aria-label="Video CRF" type="number" min={0} max={51} value={profileDraft.video_crf} onChange={e=>setProfileDraft(v=>({...v,video_crf:Number(e.target.value)}))} style={input}/>
          <select aria-label="Audio codec" value={profileDraft.audio_codec} onChange={e=>setProfileDraft(v=>({...v,audio_codec:e.target.value}))} style={input}>{(profileDraft.container==='mp4'?['aac','none']:['opus','none']).map(v=><option key={v}>{v}</option>)}</select>
          <input aria-label="Render concurrency" type="number" min={1} max={8} value={profileDraft.render_concurrency} onChange={e=>setProfileDraft(v=>({...v,render_concurrency:Number(e.target.value)}))} style={input}/>
          <input aria-label="Priority" type="number" min={0} max={100} value={profileDraft.priority} onChange={e=>setProfileDraft(v=>({...v,priority:Number(e.target.value)}))} style={input}/>
          <label style={{fontSize:12,display:'flex',alignItems:'center',gap:6}}><input type="checkbox" checked={profileDraft.is_default} onChange={e=>setProfileDraft(v=>({...v,is_default:e.target.checked}))}/> Default profile</label>
          <button disabled={busy} style={button}>{editingProfileId?'Create new version':'Create profile'}</button>{editingProfileId&&<button type="button" onClick={()=>setEditingProfileId(null)} style={{...button,background:'#edf3f9',color:'#173f72'}}>Cancel edit</button>}
        </form>
        {renderProfiles.map(profile=><div key={profile.id} style={{display:'flex',justifyContent:'space-between',gap:10,alignItems:'center',flexWrap:'wrap',padding:'9px 0',borderTop:'1px solid #edf0f5'}}>
          <div><strong>{profile.name} · v{profile.version}</strong><div style={{fontSize:12,color:'#68788e'}}>{profile.profile_key} · {profile.width}×{profile.height} · {profile.fps} FPS · {profile.container}/{profile.video_codec} · CRF {profile.video_crf} · {profile.audio_codec} · priority {profile.priority}{profile.is_default?' · default':''}</div></div>
          <button disabled={busy||profile.is_archived} onClick={()=>editRenderProfile(profile)} style={{...button,background:'#edf3f9',color:'#173f72'}}>Edit version</button><button disabled={busy||profile.is_archived} onClick={()=>void archiveRenderProfile(profile)} style={{...button,background:'#fff1f0',color:'#b42318'}}>Archive</button>
        </div>)}
      </section>
      <section style={panel}>
        <h2>Worker runtime health</h2>
        <p style={{fontSize:13,color:'#68788e'}}>Heartbeat is recorded through FastAPI and PostgreSQL. A worker is considered stale after 90 seconds without a heartbeat.</p>
        {workers.length===0&&<p style={{fontSize:12,color:'#68788e'}}>No worker heartbeat has been recorded yet.</p>}
        {workers.map(worker=><div key={worker.worker_id} style={{display:'flex',justifyContent:'space-between',alignItems:'center',gap:10,padding:'9px 0',borderTop:'1px solid #edf0f5',flexWrap:'wrap'}}>
          <div><strong>{worker.worker_type==='render'?'Remotion Render Worker':'Media Worker'} · {worker.runtime_status}</strong><div style={{fontSize:12,color:'#68788e'}}>{worker.worker_id} · {worker.hostname} · {worker.version||'version unavailable'}</div></div>
          <div style={{fontSize:12,color:'#68788e'}}>Last heartbeat {new Date(worker.last_seen_at).toLocaleString()}</div>
        </div>)}
      </section>
            <section style={panel}>
        <h2>Voice-over / TTS worker operations</h2>
        {adminMediaJobs.map(job=><div key={job.id} style={{padding:'9px 0',borderTop:'1px solid #edf0f5',display:'flex',justifyContent:'space-between',gap:10,flexWrap:'wrap'}}>
          <div><strong>{job.project_name} · {job.status}</strong><div style={{fontSize:12,color:'#68788e'}}>{job.provider_key}/{job.model_key} · {job.voice_key} · attempt {job.attempt_count}/{job.max_attempts} · {job.error_code||job.asset_id||job.id}</div></div>
          <div><div style={{fontSize:12,color:'#68788e'}}>Worker: {job.worker_id||'not claimed'}<br/>{job.lease_expires_at?'Lease '+new Date(job.lease_expires_at).toLocaleTimeString():'No active lease'}</div>{['failed','provider_unavailable'].includes(job.status)&&<button disabled={busy} onClick={()=>void retryOperationalJob('media',job.id)} style={{...button,marginTop:6}}>Retry job</button>}</div>
        </div>)}
      </section>
<section style={panel}>
        <h2>Motion component registry</h2>
        <p style={{fontSize:13,color:'#68788e'}}>Only versioned, compiled allowlisted components are executable. Disabled components are rejected on new timeline saves and render submissions.</p>
        {motionComponents.map(item=><div key={item.component_key} style={{display:'flex',justifyContent:'space-between',alignItems:'center',gap:10,padding:'8px 0',borderTop:'1px solid #edf0f5',flexWrap:'wrap'}}>
          <div><strong>{item.component_key}</strong><div style={{fontSize:12,color:'#68788e'}}>{item.category} · v{item.component_version} · {item.reason||'No change reason'}</div></div>
          <button disabled={busy} onClick={()=>void toggleMotionComponent(item)} style={{...button,background:item.enabled?'#fff1f0':'#ecfdf3',color:item.enabled?'#b42318':'#176b45'}}>{item.enabled?'Disable':'Enable'}</button>
        </div>)}
      </section>
      <section style={panel}>
        <h2>Remotion render worker operations</h2>
        {adminRenderJobs.map(job=><div key={job.id} style={{padding:'9px 0',borderTop:'1px solid #edf0f5',display:'flex',justifyContent:'space-between',gap:10,flexWrap:'wrap'}}>
          <div><strong>{job.project_name} · {job.status} · {job.progress_percent}%</strong><div style={{fontSize:12,color:'#68788e'}}>{job.workspace_name} · {job.render_profile||'profile unavailable'} · attempt {job.attempt_count} · {job.latest_attempt_status||'not claimed'}</div></div>
          <div><div style={{fontSize:12,color:'#68788e'}}>Worker: {job.worker_id||'queued'}<br/>{job.lease_expires_at?'Lease '+new Date(job.lease_expires_at).toLocaleTimeString():'No active lease'}</div>{job.status==='failed'&&<button disabled={busy} onClick={()=>void retryOperationalJob('render',job.id)} style={{...button,marginTop:6}}>Retry job</button>}</div>
        </div>)}
      </section>
      <section style={panel}><h2>Workspace administration</h2>{workspaces.map(workspace => <div key={workspace.id} style={{ padding: '10px 0', borderTop: '1px solid #edf0f5', display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}><div><strong>{workspace.name}</strong><div style={{ fontSize: 12, color: '#68788e' }}>{workspace.slug} · {workspace.active_members} active members · {workspace.projects} projects · owner {workspace.owner_user_id}</div></div><div style={{display:'flex',gap:8,flexWrap:'wrap'}}><button onClick={() => void loadMembers(workspace.id)} style={{ ...button, background: '#edf3f9', color: '#173f72' }}>Manage members</button><button onClick={() => void loadQuota(workspace.id)} style={{...button,background:'#eaf3ff',color:'#173f72'}}>Quota</button></div></div>)}
        {selectedWorkspace && <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid #dce3ed' }}><h3>Membership · {workspaces.find(w => w.id === selectedWorkspace)?.name}</h3>{quotaStart&&quotaEnd&&<div style={{marginTop:16,paddingTop:14,borderTop:'1px solid #dce3ed'}}><h3>Quota · {workspaces.find(w=>w.id===selectedWorkspace)?.name}</h3>{quotaSummary&&<p style={{fontSize:12,color:'#68788e'}}>Consumed: {quotaSummary.consumed_microusd} µUSD · Reserved: {quotaSummary.reserved_microusd} µUSD · Available: {quotaSummary.available_microusd} µUSD</p>}<form onSubmit={saveQuota} style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(180px,1fr))',gap:8}}><label style={{fontSize:12}}>Quota limit (µUSD)<input value={quotaLimit} onChange={e=>setQuotaLimit(e.target.value)} type="number" min="1" required style={input}/></label><label style={{fontSize:12}}>Period start<input value={quotaStart} onChange={e=>setQuotaStart(e.target.value)} type="datetime-local" required style={input}/></label><label style={{fontSize:12}}>Period end<input value={quotaEnd} onChange={e=>setQuotaEnd(e.target.value)} type="datetime-local" required style={input}/></label><label style={{fontSize:12}}>Status<select value={quotaStatus} onChange={e=>setQuotaStatus(e.target.value as 'active'|'paused')} style={input}><option value="active">Active</option><option value="paused">Paused</option></select></label><button disabled={busy} style={button}>Save quota account</button></form><div style={{marginTop:14,display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(190px,1fr))',gap:8}}><label style={{fontSize:12}}>TTS rate / 1,000 chars (µUSD)<input type="number" min="1" value={voiceoverRate} onChange={e=>setVoiceoverRate(e.target.value)} style={input}/><button type="button" disabled={busy} onClick={()=>void saveQuotaRate('voiceover_per_1000_chars',voiceoverRate,'1000 characters')} style={{...button,marginTop:6}}>Save TTS rate</button></label><label style={{fontSize:12}}>Render rate / second (µUSD)<input type="number" min="1" value={renderRate} onChange={e=>setRenderRate(e.target.value)} style={input}/><button type="button" disabled={busy} onClick={()=>void saveQuotaRate('render_per_second',renderRate,'second')} style={{...button,marginTop:6}}>Save render rate</button></label></div></div>}{members.map(member => <div key={member.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, padding: '9px 0', borderTop: '1px solid #edf0f5', flexWrap: 'wrap' }}><div><strong>{member.display_name || member.user_id}</strong><div style={{ fontSize: 12, color: '#68788e' }}>{member.status} · {member.role}</div></div><div style={{ display: 'flex', gap: 8 }}><select aria-label={'Role ' + member.user_id} value={member.role} disabled={member.role === 'owner' || busy} onChange={event => void updateMemberRole(member, event.target.value)} style={{ ...input, width: 130 }}><option value="admin">Admin</option><option value="editor">Editor</option><option value="member">Member</option><option value="viewer">Viewer</option><option value="billing">Billing</option></select>{member.role !== 'owner' && member.status === 'active' && <button disabled={busy} onClick={() => void removeMember(member)} style={{ ...button, background: '#fff1f0', color: '#b42318' }}>Remove</button>}</div></div>)}</div>}
      </section>
      <section style={panel}><h2>Invitation administration</h2>{invitations.filter(inv => !inv.accepted_at && !inv.cancelled_at).map(invitation => <div key={invitation.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, padding: '9px 0', borderTop: '1px solid #edf0f5', flexWrap: 'wrap' }}><div><strong>{invitation.email}</strong><div style={{ fontSize: 12, color: '#68788e' }}>{invitation.workspace_name} · {invitation.role} · {invitation.delivery_status} · expires {new Date(invitation.expires_at).toLocaleString()}</div></div><button disabled={busy} onClick={() => void cancelInvitation(invitation)} style={{ ...button, background: '#fff1f0', color: '#b42318' }}>Cancel</button></div>)}</section>
      <section style={panel}><h2>Project oversight</h2>{projects.map(project => <div key={project.id} style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center', padding: '10px 0', borderTop: '1px solid #edf0f5', flexWrap: 'wrap' }}><div><strong>{project.name}</strong><div style={{ fontSize: 12, color: '#68788e' }}>{project.workspace_name} · {project.production_mode} · {project.status}</div></div>{project.status === 'archived' ? <button disabled={busy} onClick={() => void updateProjectStatus(project, 'draft')} style={{ ...button, background: '#edf3f9', color: '#173f72' }}>Restore</button> : <button disabled={busy || project.status === 'deleted'} onClick={() => void updateProjectStatus(project, 'archived')} style={{ ...button, background: '#fff1f0', color: '#b42318' }}>Archive</button>}</div>)}</section>
      <section style={panel}><h2>Platform audit trail</h2>{audit.map(entry => <div key={entry.id} style={{ padding: '9px 0', borderTop: '1px solid #edf0f5' }}><strong>{entry.action}</strong><div style={{ fontSize: 12, color: '#68788e' }}>{entry.resource_type}:{entry.resource_id} · actor {entry.actor_user_id} · {new Date(entry.created_at).toLocaleString()}</div></div>)}</section>
    </>}
  </main>;
}
