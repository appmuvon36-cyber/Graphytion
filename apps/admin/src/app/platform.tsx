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
  const [users, setUsers] = useState<User[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [audit, setAudit] = useState<Audit[]>([]);
  const [selectedWorkspace, setSelectedWorkspace] = useState('');
  const [members, setMembers] = useState<Member[]>([]);
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
      const [o, u, w, p, a, i, pa, llm] = await Promise.all([
        request<{data: Overview}>('/admin/overview'),
        request<Page<User>>('/admin/users?page=' + page + '&per_page=25&q=' + encodeURIComponent(query)),
        request<Page<Workspace>>('/admin/workspaces?page=1&per_page=50&q=' + encodeURIComponent(query)),
        request<Page<Project>>('/admin/projects?page=1&per_page=50&q=' + encodeURIComponent(query)),
        request<Page<Audit>>('/admin/audit-logs?page=1&per_page=30'),
        request<Page<Invitation>>('/admin/invitations?page=1&per_page=50'),
        request<{data: PlatformAdminRecord[]}>('/admin/platform-admins'),
        request<{data: LlmStatus}>('/admin/llm/providers'),
      ]);
      setOverview(o.data); setUsers(u.data); setWorkspaces(w.data); setProjects(p.data); setAudit(a.data); setInvitations(i.data); setPlatformAdmins(pa.data); setLlmStatus(llm.data);
      setDenied(false);
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
      <section style={panel}><h2>Workspace administration</h2>{workspaces.map(workspace => <div key={workspace.id} style={{ padding: '10px 0', borderTop: '1px solid #edf0f5', display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}><div><strong>{workspace.name}</strong><div style={{ fontSize: 12, color: '#68788e' }}>{workspace.slug} · {workspace.active_members} active members · {workspace.projects} projects · owner {workspace.owner_user_id}</div></div><button onClick={() => void loadMembers(workspace.id)} style={{ ...button, background: '#edf3f9', color: '#173f72' }}>Manage members</button></div>)}
        {selectedWorkspace && <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid #dce3ed' }}><h3>Membership · {workspaces.find(w => w.id === selectedWorkspace)?.name}</h3>{members.map(member => <div key={member.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, padding: '9px 0', borderTop: '1px solid #edf0f5', flexWrap: 'wrap' }}><div><strong>{member.display_name || member.user_id}</strong><div style={{ fontSize: 12, color: '#68788e' }}>{member.status} · {member.role}</div></div><div style={{ display: 'flex', gap: 8 }}><select aria-label={'Role ' + member.user_id} value={member.role} disabled={member.role === 'owner' || busy} onChange={event => void updateMemberRole(member, event.target.value)} style={{ ...input, width: 130 }}><option value="admin">Admin</option><option value="editor">Editor</option><option value="member">Member</option><option value="viewer">Viewer</option><option value="billing">Billing</option></select>{member.role !== 'owner' && member.status === 'active' && <button disabled={busy} onClick={() => void removeMember(member)} style={{ ...button, background: '#fff1f0', color: '#b42318' }}>Remove</button>}</div></div>)}</div>}
      </section>
      <section style={panel}><h2>Invitation administration</h2>{invitations.filter(inv => !inv.accepted_at && !inv.cancelled_at).map(invitation => <div key={invitation.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, padding: '9px 0', borderTop: '1px solid #edf0f5', flexWrap: 'wrap' }}><div><strong>{invitation.email}</strong><div style={{ fontSize: 12, color: '#68788e' }}>{invitation.workspace_name} · {invitation.role} · {invitation.delivery_status} · expires {new Date(invitation.expires_at).toLocaleString()}</div></div><button disabled={busy} onClick={() => void cancelInvitation(invitation)} style={{ ...button, background: '#fff1f0', color: '#b42318' }}>Cancel</button></div>)}</section>
      <section style={panel}><h2>Project oversight</h2>{projects.map(project => <div key={project.id} style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center', padding: '10px 0', borderTop: '1px solid #edf0f5', flexWrap: 'wrap' }}><div><strong>{project.name}</strong><div style={{ fontSize: 12, color: '#68788e' }}>{project.workspace_name} · {project.production_mode} · {project.status}</div></div>{project.status === 'archived' ? <button disabled={busy} onClick={() => void updateProjectStatus(project, 'draft')} style={{ ...button, background: '#edf3f9', color: '#173f72' }}>Restore</button> : <button disabled={busy || project.status === 'deleted'} onClick={() => void updateProjectStatus(project, 'archived')} style={{ ...button, background: '#fff1f0', color: '#b42318' }}>Archive</button>}</div>)}</section>
      <section style={panel}><h2>Platform audit trail</h2>{audit.map(entry => <div key={entry.id} style={{ padding: '9px 0', borderTop: '1px solid #edf0f5' }}><strong>{entry.action}</strong><div style={{ fontSize: 12, color: '#68788e' }}>{entry.resource_type}:{entry.resource_id} · actor {entry.actor_user_id} · {new Date(entry.created_at).toLocaleString()}</div></div>)}</section>
    </>}
  </main>;
}
