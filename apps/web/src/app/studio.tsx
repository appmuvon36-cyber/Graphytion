'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiClientError, createApiClient } from '@graphytion/api-client';
import type { ProfileApi, WorkspaceApi, VideoProjectApi, WorkspacePermissionsApi, WorkspaceMemberApi, WorkspaceInvitationApi } from '@graphytion/contracts';

type Profile = ProfileApi;
type Workspace = WorkspaceApi;
type Project = VideoProjectApi;\ntype Member = WorkspaceMemberApi;\ntype Invitation = WorkspaceInvitationApi & { delivery_status?: string; delivery_attempts?: number; sent_at?: string | null };
type AuthResult = { authenticated?:boolean; user?:{id:string;email:string}|null };
const apiBase = typeof window !== 'undefined' ? window.location.origin + '/api' : 'http://localhost:3000/api';

export default function Studio() {
  const [access,setAccess] = useState('');
  const [profile,setProfile] = useState<Profile|null>(null);
  const [email,setEmail] = useState('');
  const [password,setPassword] = useState('');
  const [displayName,setDisplayName] = useState('');
  const [mode,setMode] = useState<'login'|'signup'>('login');
  const [workspaces,setWorkspaces] = useState<Workspace[]>([]);
  const [permissions,setPermissions] = useState<string[]>([]);\n  const [members,setMembers] = useState<Member[]>([]);\n  const [invitations,setInvitations] = useState<Invitation[]>([]);\n  const [inviteEmail,setInviteEmail] = useState('');\n  const [inviteRole,setInviteRole] = useState<'member'|'viewer'|'editor'|'admin'|'billing'>('member');
  const [workspaceId,setWorkspaceId] = useState('');
  const [projects,setProjects] = useState<Project[]>([]);
  const [projectTotal,setProjectTotal] = useState(0);
  const [projectOffset,setProjectOffset] = useState(0);
  const [projectStatus,setProjectStatus] = useState('');
  const [projectSort,setProjectSort] = useState<'updated_at'|'created_at'|'name'>('updated_at');
  const [workspaceName,setWorkspaceName] = useState('');
  const [workspaceSlug,setWorkspaceSlug] = useState('');
  const [workspaceEditName,setWorkspaceEditName] = useState('');
  const [projectName,setProjectName] = useState('');
  const [projectDescription,setProjectDescription] = useState('');
  const [search,setSearch] = useState('');
  const [notice,setNotice] = useState('');
  const [error,setError] = useState('');
  const [busy,setBusy] = useState(false);
  const [loadingAccount,setLoadingAccount] = useState(false);
  const [loadingProjects,setLoadingProjects] = useState(false);
  const [profileName,setProfileName] = useState('');
  const [profileBio,setProfileBio] = useState('');
  const [newPassword,setNewPassword] = useState('');
  const [passwordRecovery,setPasswordRecovery] = useState(false);
  const [needsVerification,setNeedsVerification] = useState(false);
  const [avatarFile,setAvatarFile] = useState<File|null>(null);
  const [avatarUrl,setAvatarUrl] = useState('');
  const [invitationToken,setInvitationToken] = useState('');
  const [editingProject,setEditingProject] = useState<Project|null>(null);
  const [editName,setEditName] = useState('');
  const [editDescription,setEditDescription] = useState('');
  const [projectDetail,setProjectDetail] = useState<Record<string,unknown>|null>(null);

  const api = useMemo(()=>createApiClient({baseUrl:apiBase}),[]);
  const publicApi = api;
  const call = useCallback(async <T,>(path:string,init:RequestInit={})=>{
    try { return await api.request<T>(path,init); }
    catch (e) {
      if (e instanceof ApiClientError && e.status===401) {
        setAccess('');
        setProfile(null);
        setWorkspaces([]);
        setProjects([]);
      }
      throw e;
    }
  },[api]);

  const loadWorkspaceData=useCallback(async(id:string,filters:{q?:string;status?:string;sort?:string;offset?:number}={})=>{
    if(!id){setProjects([]);setProjectTotal(0);return;}
    setLoadingProjects(true);
    try{
      const params=new URLSearchParams({limit:'25',offset:String(filters.offset??0),sort:filters.sort||'updated_at',direction:'desc'});
      if(filters.q?.trim())params.set('q',filters.q.trim());
      if(filters.status)params.set('status',filters.status);
      const result=await call<{data:Project[];page:{total:number}}>('/workspaces/'+id+'/projects?'+params.toString());
      setProjects(result.data);setProjectTotal(result.page.total);
    } finally { setLoadingProjects(false); }
  },[call]);

  const loadAccount=useCallback(async()=>{
    const [me,ws]=await Promise.all([
      call<{data:Profile}>('/me'),
      call<{data:Workspace[]}>('/workspaces')
    ]);
    setProfile(me.data); setProfileName(me.data.display_name||''); setProfileBio(me.data.bio||'');
    if(me.data.avatar_path){const avatar=await call<{data:{signed_url:string}}>('/me/avatar-url');setAvatarUrl(avatar.data.signed_url);}else{setAvatarUrl('');}
    setWorkspaces(ws.data);
    const selected=workspaceId && ws.data.some(w=>w.id===workspaceId) ? workspaceId : (ws.data[0]?.id||'');
    setWorkspaceId(selected);
    setWorkspaceEditName(ws.data.find(w=>w.id===selected)?.name||'');
    if(selected){const permissionResult=await call<{data:WorkspacePermissionsApi}>('/workspaces/'+selected+'/permissions');const allowed=permissionResult.data.permissions;setPermissions(allowed);const [m,i]=await Promise.all([allowed.includes('member.read')?call<{data:Member[]}>('/workspaces/'+selected+'/members'):Promise.resolve({data:[] as Member[]}),allowed.includes('member.manage')?call<{data:Invitation[]}>('/workspaces/'+selected+'/invitations'):Promise.resolve({data:[] as Invitation[]})]);setMembers(m.data);setInvitations(i.data);await loadWorkspaceData(selected);}else{setPermissions([]);setProjects([]);setMembers([]);setInvitations([]);}
  },[call,loadWorkspaceData,workspaceId]);

  useEffect(()=>{
    let active=true;
    const currentUrl=new URL(window.location.href);
    if(currentUrl.searchParams.get('recovery')==='1'){
      setPasswordRecovery(true);
      setNotice('Verifikasi pemulihan berhasil. Atur password baru.');
      currentUrl.searchParams.delete('recovery');
      window.history.replaceState({},document.title,currentUrl.pathname+currentUrl.search+currentUrl.hash);
    }
    const fragment=new URLSearchParams(window.location.hash.replace(/^#/,''));
    const invitation=fragment.get('invite');
    if(invitation){
      setInvitationToken(invitation);
      window.history.replaceState({},document.title,window.location.pathname+window.location.search);
      setNotice('Undangan workspace ditemukan. Masuk atau daftar dengan email penerima untuk menerimanya.');
    } else if(fragment.has('access_token')||fragment.has('refresh_token')){
      window.history.replaceState({},document.title,window.location.pathname+window.location.search);
      setNotice('Tautan autentikasi lama dibersihkan. Silakan masuk kembali untuk membuat sesi aman.');
    }
    fetch('/api/csrf',{credentials:'include',cache:'no-store'}).finally(()=>{
      api.request<{authenticated:boolean}>('/auth/session')
        .then(result=>{if(active)setAccess(result.authenticated?'cookie-session':'');})
        .catch(()=>{if(active)setAccess('');});
    });
    return ()=>{active=false;};
  },[api]);
  useEffect(()=>{
    if(!access)return;
    setLoadingAccount(true);
    loadAccount().catch(e=>setError(e instanceof Error?e.message:'Tidak dapat memuat akun')).finally(()=>setLoadingAccount(false));
  },[access,loadAccount]);

  useEffect(()=>{
    if(!access||!workspaceId)return;
    const timer=window.setTimeout(()=>{
      loadWorkspaceData(workspaceId,{q:search,status:projectStatus,sort:projectSort,offset:projectOffset})
        .catch(e=>setError(e instanceof Error?e.message:'Tidak dapat memuat project'));
    },220);
    return ()=>window.clearTimeout(timer);
  },[access,workspaceId,search,projectStatus,projectSort,projectOffset,loadWorkspaceData]);

  async function authenticate(event:React.FormEvent<HTMLFormElement>){
    event.preventDefault(); setBusy(true); setError(''); setNotice('');
    try {
      const body=await publicApi.request<AuthResult>(mode==='login'?'/auth/login':'/auth/signup',{method:'POST',body:JSON.stringify(mode==='login'?{email,password}:{email,password,display_name:displayName})});
      if(!body.authenticated){setNotice('Akun berhasil didaftarkan. Periksa email untuk verifikasi, lalu masuk setelah akun aktif.');setNeedsVerification(true);setMode('login');return;}
      setAccess('cookie-session'); setNotice('Berhasil masuk.');
    } catch(e){setError(e instanceof Error?e.message:'Autentikasi gagal');} finally{setBusy(false);}
  }
  async function logout(){
    try{await publicApi.request('/auth/logout',{method:'POST'});}catch{}
    setAccess('');setProfile(null);setWorkspaces([]);setProjects([]);setMembers([]);setInvitations([]);setPermissions([]);setNotice('Sesi telah diakhiri.');
  }
  async function resendVerification(){
    setBusy(true);setError('');
    try{await publicApi.request('/auth/resend-verification',{method:'POST',body:JSON.stringify({email})});setNotice('Jika akun membutuhkan verifikasi, email telah diminta untuk dikirim ulang.');}
    catch(e){setError(e instanceof Error?e.message:'Tidak dapat mengirim ulang verifikasi');}finally{setBusy(false);}
  }
  async function changePassword(event:React.FormEvent<HTMLFormElement>){
    event.preventDefault();setBusy(true);setError('');
    try{await call('/auth/password',{method:'POST',body:JSON.stringify({password:newPassword})});setNewPassword('');setPasswordRecovery(false);setNotice('Password berhasil diperbarui.');}
    catch(e){setError(e instanceof Error?e.message:'Password tidak dapat diperbarui');}finally{setBusy(false);}
  }
  async function recover(){
    setBusy(true);setError('');setNotice('');
    try{await publicApi.request('/auth/recovery',{method:'POST',body:JSON.stringify({email})});setNotice('Jika email terdaftar, instruksi pemulihan akan dikirim.');}
    catch{setError('Permintaan pemulihan tidak dapat diproses.');}finally{setBusy(false);}
  }
  async function createWorkspace(event:React.FormEvent<HTMLFormElement>){
    event.preventDefault();setBusy(true);setError('');
    try{await call('/workspaces',{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()},body:JSON.stringify({name:workspaceName,slug:workspaceSlug})});setWorkspaceName('');setWorkspaceSlug('');await loadAccount();setNotice('Workspace berhasil dibuat.');}
    catch(e){setError(e instanceof Error?e.message:'Gagal membuat workspace');}finally{setBusy(false);}
  }
  async function updateWorkspace(event:React.FormEvent<HTMLFormElement>){
    event.preventDefault();if(!workspaceId)return;setBusy(true);setError('');
    try{await call('/workspaces/'+workspaceId,{method:'PATCH',body:JSON.stringify({name:workspaceEditName})});await loadAccount();setNotice('Workspace diperbarui.');}
    catch(e){setError(e instanceof Error?e.message:'Gagal memperbarui workspace');}finally{setBusy(false);}
  }
  async function deleteWorkspace(){
    if(!workspaceId||!permissions.includes('workspace.delete'))return;
    if(!window.confirm('Hapus workspace ini? Workspace hanya dapat dihapus jika belum memiliki project.'))return;
    setBusy(true);setError('');
    try{await call('/workspaces/'+workspaceId,{method:'DELETE'});setWorkspaceId('');setPermissions([]);await loadAccount();setNotice('Workspace berhasil dihapus.');}
    catch(e){setError(e instanceof Error?e.message:'Workspace tidak dapat dihapus');}finally{setBusy(false);}
  }
  async function leaveWorkspace(){
    if(!workspaceId||selectedRole==='owner')return;
    if(!window.confirm('Keluar dari workspace ini?'))return;setBusy(true);setError('');
    try{await call('/workspaces/'+workspaceId+'/leave',{method:'POST'});setWorkspaceId('');await loadAccount();setNotice('Anda telah keluar dari workspace.');}
    catch(e){setError(e instanceof Error?e.message:'Tidak dapat keluar dari workspace');}finally{setBusy(false);}
  }
  async function createInvitation(event:React.FormEvent<HTMLFormElement>){
    event.preventDefault();if(!workspaceId||!permissions.includes('member.manage'))return;setBusy(true);setError('');setNotice('');
    try{const result=await call<{data:{delivery_status?:string}}>('/workspaces/'+workspaceId+'/invitations',{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()},body:JSON.stringify({email:inviteEmail,role:inviteRole})});setInviteEmail('');setNotice(result.data.delivery_status==='sent'?'Provider menerima permintaan pengiriman invitation.':'Invitation dibuat; status pengiriman belum terkonfirmasi.');await loadAccount();}
    catch(e){setError(e instanceof Error?e.message:'Gagal membuat invitation');}finally{setBusy(false);}
  }
  async function changeMemberRole(member:Member,nextRole:string){
    if(!workspaceId)return;setBusy(true);setError('');
    try{await call('/workspaces/'+workspaceId+'/members/'+member.id,{method:'PATCH',body:JSON.stringify({role:nextRole})});await loadAccount();setNotice('Role anggota diperbarui.');}
    catch(e){setError(e instanceof Error?e.message:'Gagal memperbarui role anggota');}finally{setBusy(false);}
  }
  async function removeMember(member:Member){
    if(!workspaceId||!window.confirm('Keluarkan anggota ini dari workspace?'))return;setBusy(true);setError('');
    try{await call('/workspaces/'+workspaceId+'/members/'+member.id,{method:'DELETE'});await loadAccount();setNotice('Anggota dikeluarkan dari workspace.');}
    catch(e){setError(e instanceof Error?e.message:'Gagal mengeluarkan anggota');}finally{setBusy(false);}
  }
  async function cancelInvitation(invitation:Invitation){
    if(!workspaceId||!window.confirm('Batalkan invitation untuk '+invitation.email+'?'))return;setBusy(true);setError('');
    try{await call('/workspaces/'+workspaceId+'/invitations/'+invitation.id,{method:'DELETE'});await loadAccount();setNotice('Invitation dibatalkan.');}
    catch(e){setError(e instanceof Error?e.message:'Gagal membatalkan invitation');}finally{setBusy(false);}
  }
  async function createProject(event:React.FormEvent<HTMLFormElement>){
    event.preventDefault();if(!workspaceId)return;setBusy(true);setError('');
    try{await call('/workspaces/'+workspaceId+'/projects',{method:'POST',headers:{'Idempotency-Key':crypto.randomUUID()},body:JSON.stringify({name:projectName,description:projectDescription||null,production_mode:'motion_graphic',default_language:'id-ID',aspect_ratio:'16:9',width:1920,height:1080,fps:30,settings:{}})});setProjectName('');setProjectDescription('');await loadWorkspaceData(workspaceId,{q:search,status:projectStatus,sort:projectSort,offset:projectOffset});setNotice('Project tersimpan.');}
    catch(e){setError(e instanceof Error?e.message:'Gagal membuat project');}finally{setBusy(false);}
  }
  async function saveProfile(event:React.FormEvent<HTMLFormElement>){
    event.preventDefault();setBusy(true);setError('');
    try{const result=await call<{data:Profile}>('/me',{method:'PATCH',body:JSON.stringify({display_name:profileName,bio:profileBio})});setProfile(result.data);setNotice('Profil diperbarui.');}
    catch(e){setError(e instanceof Error?e.message:'Gagal memperbarui profil');}finally{setBusy(false);}
  }
  async function acceptInvitation(){
    if(!invitationToken)return;
    setBusy(true);setError('');
    try{await call('/invitations/accept',{method:'POST',body:JSON.stringify({token:invitationToken})});setInvitationToken('');await loadAccount();setNotice('Invitation diterima dan workspace ditambahkan.');}
    catch(e){setError(e instanceof Error?e.message:'Invitation tidak dapat diterima');}finally{setBusy(false);}
  }
  async function showProjectDetail(project:Project){
    setError('');
    try{const result=await call<{data:Record<string,unknown>}>('/projects/'+project.id);setProjectDetail(result.data);}
    catch(e){setError(e instanceof Error?e.message:'Detail project tidak dapat dimuat');}
  }
  async function saveProject(event:React.FormEvent<HTMLFormElement>){
    event.preventDefault();if(!editingProject)return;setBusy(true);setError('');
    try{await call('/projects/'+editingProject.id,{method:'PATCH',body:JSON.stringify({name:editName,description:editDescription||null})});setEditingProject(null);await loadWorkspaceData(workspaceId,{q:search,status:projectStatus,sort:projectSort,offset:projectOffset});setNotice('Project diperbarui.');}
    catch(e){setError(e instanceof Error?e.message:'Gagal memperbarui project');}finally{setBusy(false);}
  }
  async function uploadAvatar(event:React.FormEvent<HTMLFormElement>){
    event.preventDefault(); if(!avatarFile)return; setBusy(true);setError('');
    try{const form=new FormData();form.append('file',avatarFile);const result=await call<{data:Profile}>('/me/avatar',{method:'POST',body:form});setProfile(result.data);const avatar=await call<{data:{signed_url:string}}>('/me/avatar-url');setAvatarUrl(avatar.data.signed_url);setAvatarFile(null);setNotice('Avatar tersimpan secara private.');}
    catch(e){setError(e instanceof Error?e.message:'Upload avatar gagal');}finally{setBusy(false);}
  }
  async function changeStatus(project:Project,action:'archive'|'restore'|'delete'){
    if(action==='delete'&&!window.confirm('Hapus project ini? Project akan ditandai deleted.'))return;
    setBusy(true);setError('');
    try{await call('/projects/'+project.id+(action==='delete'?'':'/'+action),{method:action==='delete'?'DELETE':'POST'});await loadWorkspaceData(workspaceId,{q:search,status:projectStatus,sort:projectSort,offset:projectOffset});setNotice('Status project diperbarui.');}
    catch(e){setError(e instanceof Error?e.message:'Operasi project gagal');}finally{setBusy(false);}
  }

  const visibleProjects=projects;
  const selectedRole=workspaces.find(w=>w.id===workspaceId)?.role||'';
  const canEditProject=permissions.includes('project.update');
  const canArchiveProject=permissions.includes('project.archive');
  const canDeleteProject=permissions.includes('project.delete');
  const field:React.CSSProperties={width:'100%',padding:'12px 14px',border:'1px solid #dce3ed',borderRadius:10,fontSize:14,background:'#fff',color:'#142033'};
  const button:React.CSSProperties={border:0,borderRadius:10,padding:'11px 15px',background:'#173f72',color:'#fff',fontWeight:700,cursor:'pointer'};
  const card:React.CSSProperties={background:'#fff',border:'1px solid #e5eaf1',borderRadius:16,padding:20,boxShadow:'0 6px 24px rgba(20,32,51,.04)'};

  if(!access) return <main style={{maxWidth:480,margin:'8vh auto',padding:24}}>
    <p style={{fontSize:12,fontWeight:800,letterSpacing:'.14em',color:'#47719e'}}>GRAPHYTION STUDIO</p>
    <h1 style={{fontSize:34,letterSpacing:'-.04em'}}>Produksi motion graphic, dalam satu workspace.</h1>
    <p style={{color:'#65758a',lineHeight:1.6}}>Masuk untuk mengelola workspace dan project produksi. Autentikasi diproses oleh Supabase Auth melalui FastAPI.</p>
    <form onSubmit={authenticate} style={{...card,display:'grid',gap:12}}>
      {mode==='signup'&&<input aria-label="Nama" placeholder="Nama lengkap" value={displayName} onChange={e=>setDisplayName(e.target.value)} required style={field}/>}
      <input aria-label="Email" type="email" placeholder="Email" value={email} onChange={e=>setEmail(e.target.value)} required style={field}/>
      <input aria-label="Password" type="password" placeholder="Password (minimal 10 karakter)" minLength={10} value={password} onChange={e=>setPassword(e.target.value)} required style={field}/>
      <button disabled={busy} style={button}>{busy?'Memproses…':mode==='login'?'Masuk':'Buat akun'}</button>
      <button type="button" onClick={()=>setMode(mode==='login'?'signup':'login')} style={{...button,background:'#edf3f9',color:'#173f72'}}>{mode==='login'?'Daftar akun baru':'Kembali ke login'}</button>
      {mode==='login'&&<button type="button" onClick={recover} style={{border:0,background:'transparent',color:'#47719e',cursor:'pointer'}}>Lupa password?</button>}
      {needsVerification&&<button type="button" disabled={busy} onClick={resendVerification} style={{border:0,background:'transparent',color:'#47719e',cursor:'pointer'}}>Kirim ulang email verifikasi</button>}

    </form>
    {error&&<p role="alert" style={{color:'#b42318'}}>{error}</p>}{notice&&<p role="status" style={{color:'#176b45'}}>{notice}</p>}
  </main>;

  return <main style={{maxWidth:1180,margin:'0 auto',padding:'36px 22px 72px'}}>
    <header style={{display:'flex',justifyContent:'space-between',alignItems:'center',gap:16,flexWrap:'wrap',marginBottom:28}}>
      <div><p style={{fontSize:11,fontWeight:800,letterSpacing:'.15em',color:'#47719e'}}>GRAPHYTION STUDIO</p><h1 style={{fontSize:32,margin:'4px 0'}}>Production workspace</h1><p style={{margin:0,color:'#68788e'}}>{profile?.display_name||'Account'} · {profile?.id}</p></div>
      <button onClick={logout} style={{...button,background:'#edf3f9',color:'#173f72'}}>Keluar</button>
    </header>
    {error&&<p role="alert" style={{padding:12,background:'#fff1f0',color:'#b42318',borderRadius:10}}>{error}</p>}{notice&&<p role="status" style={{padding:12,background:'#ecfdf3',color:'#176b45',borderRadius:10}}>{notice}</p>}{loadingAccount&&<p role="status" style={{color:'#68788e'}}>Memuat profil dan workspace…</p>}
    <section style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(260px,1fr))',gap:16,marginBottom:20}}>
      <div style={card}><h2 style={{marginTop:0,fontSize:18}}>Workspace</h2><select aria-label="Pilih workspace" value={workspaceId} onChange={e=>{const id=e.target.value;setWorkspaceId(id);setWorkspaceEditName(workspaces.find(w=>w.id===id)?.name||'');if(id){Promise.all([loadWorkspaceData(id),call<{data:WorkspacePermissionsApi}>('/workspaces/'+id+'/permissions')]).then(async([,p])=>{setPermissions(p.data.permissions);const [m,i]=await Promise.all([p.data.permissions.includes('member.read')?call<{data:Member[]}>('/workspaces/'+id+'/members'):Promise.resolve({data:[] as Member[]}),p.data.permissions.includes('member.manage')?call<{data:Invitation[]}>('/workspaces/'+id+'/invitations'):Promise.resolve({data:[] as Invitation[]})]);setMembers(m.data);setInvitations(i.data);}).catch(x=>setError(String(x)));}else{setPermissions([]);setProjects([]);setMembers([]);setInvitations([]);}}} style={field}><option value="">Pilih workspace</option>{workspaces.map(w=><option key={w.id} value={w.id}>{w.name} · {w.role}</option>)}</select><p style={{color:'#68788e',fontSize:13}}>{workspaces.length} workspace tersedia</p>{workspaceId&&<><form onSubmit={updateWorkspace} style={{display:'flex',gap:8,marginTop:8}}><input aria-label="Ubah nama workspace" value={workspaceEditName||workspaces.find(w=>w.id===workspaceId)?.name||''} onChange={e=>setWorkspaceEditName(e.target.value)} style={field}/><button disabled={busy||!permissions.includes('workspace.update')} style={button}>Simpan nama</button></form>{selectedRole!=='owner'&&<button onClick={leaveWorkspace} disabled={busy} style={{...button,background:'#fff1f0',color:'#b42318',marginTop:8}}>Keluar workspace</button>}{permissions.includes('workspace.delete')&&<button onClick={deleteWorkspace} disabled={busy} style={{...button,background:'#fff1f0',color:'#b42318',marginTop:8}}>Hapus workspace</button>}</>}<form onSubmit={createWorkspace} style={{display:'grid',gap:8,marginTop:14}}><input aria-label="Nama workspace" placeholder="Nama workspace baru" value={workspaceName} onChange={e=>setWorkspaceName(e.target.value)} required style={field}/><input aria-label="Slug workspace" placeholder="slug-workspace" value={workspaceSlug} onChange={e=>setWorkspaceSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g,''))} required style={field}/><button disabled={busy} style={button}>Buat workspace</button></form></div>
      <div style={card}><h2 style={{marginTop:0,fontSize:18}}>Profil akun</h2>{avatarUrl&&<img src={avatarUrl} alt="Avatar profil" width={72} height={72} style={{width:72,height:72,objectFit:'cover',borderRadius:'50%',marginBottom:10}}/>}<form onSubmit={saveProfile} style={{display:'grid',gap:8}}><input aria-label="Nama tampilan" placeholder="Nama tampilan" value={profileName} onChange={e=>setProfileName(e.target.value)} style={field}/><textarea aria-label="Bio" placeholder="Bio singkat" value={profileBio} onChange={e=>setProfileBio(e.target.value)} rows={3} style={field}/><button disabled={busy} style={button}>Simpan profil</button></form><form onSubmit={uploadAvatar} style={{display:'grid',gap:8,marginTop:14}}><input aria-label="Avatar PNG JPEG WebP" type="file" accept="image/png,image/jpeg,image/webp" onChange={e=>setAvatarFile(e.target.files?.[0]||null)}/><button disabled={busy||!avatarFile} style={{...button,background:'#edf3f9',color:'#173f72'}}>Upload avatar private</button></form>{profile?.avatar_path&&<p style={{fontSize:12,color:'#68788e'}}>Avatar: {profile.avatar_path}</p>}{passwordRecovery&&<form onSubmit={changePassword} style={{display:'grid',gap:8,marginTop:16}}><strong>Atur password baru</strong><input aria-label="Password baru" type="password" minLength={10} required value={newPassword} onChange={e=>setNewPassword(e.target.value)} style={field}/><button disabled={busy} style={button}>Simpan password baru</button></form>}</div>
    </section>
    {invitationToken&&<section style={{...card,marginBottom:18}}><h2 style={{marginTop:0,fontSize:18}}>Undangan workspace</h2><p style={{color:'#68788e',fontSize:14}}>Tautan undangan terdeteksi. Pastikan Anda masuk menggunakan alamat email yang menerima undangan.</p><button type="button" onClick={acceptInvitation} disabled={busy} style={button}>{busy?'Memproses…':'Terima undangan'}</button></section>}
    {workspaceId&&permissions.includes('member.read')&&<section style={{...card,marginBottom:18}}>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',gap:10,flexWrap:'wrap'}}><div><h2 style={{margin:'0 0 4px',fontSize:20}}>Workspace members</h2><p style={{margin:0,color:'#68788e',fontSize:13}}>Role dan membership divalidasi oleh FastAPI pada setiap operasi.</p></div><span style={{fontSize:13,color:'#68788e'}}>{members.length} anggota</span></div>
      {permissions.includes('member.manage')&&<form onSubmit={createInvitation} style={{display:'grid',gridTemplateColumns:'minmax(180px,1fr) 150px auto',gap:8,margin:'16px 0'}}><input aria-label="Email anggota baru" type="email" required placeholder="Email anggota" value={inviteEmail} onChange={e=>setInviteEmail(e.target.value)} style={field}/><select aria-label="Role invitation" value={inviteRole} onChange={e=>setInviteRole(e.target.value as typeof inviteRole)} style={field}><option value="member">Member</option><option value="viewer">Viewer</option><option value="editor">Editor</option><option value="billing">Billing</option>{selectedRole==='owner'&&<option value="admin">Admin</option>}</select><button disabled={busy} style={button}>Undang anggota</button></form>}
      <div style={{display:'grid',gap:7}}>{members.map(m=><div key={m.id} style={{display:'flex',justifyContent:'space-between',alignItems:'center',gap:10,padding:'10px 0',borderTop:'1px solid #edf0f5',flexWrap:'wrap'}}><div><strong>{m.display_name||m.user_id}</strong><p style={{margin:'3px 0',fontSize:12,color:'#68788e'}}>{m.status} · {m.role}</p></div><div style={{display:'flex',gap:7,alignItems:'center'}}>{permissions.includes('member.manage')&&<select aria-label={'Role '+m.user_id} value={m.role} disabled={busy||m.role==='owner'} onChange={e=>void changeMemberRole(m,e.target.value)} style={{...field,width:130}}>{selectedRole==='owner'&&<option value="admin">Admin</option>}<option value="editor">Editor</option><option value="member">Member</option><option value="viewer">Viewer</option><option value="billing">Billing</option></select>}{permissions.includes('member.manage')&&m.role!=='owner'&&<button type="button" disabled={busy} onClick={()=>void removeMember(m)} style={{...button,background:'#fff1f0',color:'#b42318'}}>Remove</button>}</div></div>)}</div>
      {permissions.includes('member.manage')&&<div style={{marginTop:14}}><strong>Pending invitations ({invitations.length})</strong>{invitations.map(i=><div key={i.id} style={{display:'flex',justifyContent:'space-between',alignItems:'center',gap:10,padding:'9px 0',borderTop:'1px solid #edf0f5',flexWrap:'wrap'}}><div><span>{i.email}</span><p style={{margin:'3px 0',fontSize:12,color:'#68788e'}}>{i.role} · {i.delivery_status||'pending'}</p></div><button type="button" disabled={busy} onClick={()=>void cancelInvitation(i)} style={{...button,background:'#fff1f0',color:'#b42318'}}>Batalkan</button></div>)}</div>}
    </section>}
    <section style={card}>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',gap:12,flexWrap:'wrap'}}><div><h2 style={{margin:'0 0 4px',fontSize:21}}>Projects</h2><p style={{margin:0,color:'#68788e',fontSize:13}}>Data project berasal dari FastAPI dan Supabase.</p></div><div style={{display:'flex',gap:8,flexWrap:'wrap'}}><input aria-label="Cari project" placeholder="Cari project…" value={search} onChange={e=>{setSearch(e.target.value);setProjectOffset(0);}} style={{...field,maxWidth:220}}/><select aria-label="Filter status project" value={projectStatus} onChange={e=>{setProjectStatus(e.target.value);setProjectOffset(0);}} style={{...field,maxWidth:140}}><option value="">Semua status</option><option value="draft">Draft</option><option value="active">Active</option><option value="archived">Archived</option></select><select aria-label="Urutkan project" value={projectSort} onChange={e=>{setProjectSort(e.target.value as 'updated_at'|'created_at'|'name');setProjectOffset(0);}} style={{...field,maxWidth:150}}><option value="updated_at">Terbaru diubah</option><option value="created_at">Terbaru dibuat</option><option value="name">Nama</option></select></div></div>
      {workspaceId&&<form onSubmit={createProject} style={{display:'grid',gridTemplateColumns:'1fr 1.5fr auto',gap:8,margin:'18px 0'}}><input aria-label="Nama project" placeholder="Nama project" value={projectName} onChange={e=>setProjectName(e.target.value)} required style={field}/><input aria-label="Deskripsi project" placeholder="Deskripsi (opsional)" value={projectDescription} onChange={e=>setProjectDescription(e.target.value)} style={field}/><button disabled={busy||!canEditProject} style={button}>Project baru</button></form>}
      {!workspaceId?<p style={{padding:24,textAlign:'center',color:'#68788e'}}>Pilih atau buat workspace untuk mulai.</p>:loadingProjects?<p style={{padding:24,textAlign:'center',color:'#68788e'}}>Memuat project…</p>:visibleProjects.length===0?<p style={{padding:24,textAlign:'center',color:'#68788e'}}>Belum ada project yang cocok. Buat project pertama dari formulir di atas.</p>:<div style={{display:'grid',gap:10,marginTop:18}}>{visibleProjects.map(p=><article key={p.id} style={{display:'flex',justifyContent:'space-between',gap:12,alignItems:'center',padding:'14px 0',borderTop:'1px solid #edf0f5',flexWrap:'wrap'}}><div><strong>{p.name}</strong><p style={{margin:'4px 0',fontSize:13,color:'#68788e'}}>{p.description||'Tanpa deskripsi'} · {p.status} · {p.production_mode}</p></div><div style={{display:'flex',gap:7,flexWrap:'wrap'}}><button onClick={()=>showProjectDetail(p)} style={{...button,padding:'8px 11px',background:'#edf3f9',color:'#173f72'}}>Detail</button><a href={"/projects/"+p.id} style={{...button,padding:'8px 11px',background:'#173f72',color:'#fff',textDecoration:'none'}}>Creative Studio</a><button onClick={()=>{setEditingProject(p);setEditName(p.name);setEditDescription(p.description||'');}} disabled={!canEditProject} style={{...button,padding:'8px 11px',background:'#edf3f9',color:'#173f72'}}>Edit</button>{p.status==='archived'?<button onClick={()=>changeStatus(p,'restore')} disabled={!canArchiveProject} style={{...button,padding:'8px 11px'}}>Pulihkan</button>:<button onClick={()=>changeStatus(p,'archive')} disabled={!canArchiveProject} style={{...button,padding:'8px 11px',background:'#edf3f9',color:'#173f72'}}>Arsipkan</button>}<button onClick={()=>changeStatus(p,'delete')} disabled={!canDeleteProject} style={{...button,padding:'8px 11px',background:'#fff1f0',color:'#b42318'}}>Hapus</button></div></article>)}</div>}
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',gap:10,marginTop:18,flexWrap:'wrap'}}><span style={{fontSize:13,color:'#68788e'}}>{projectTotal} project · halaman {Math.floor(projectOffset/25)+1}</span><div style={{display:'flex',gap:8}}><button type="button" disabled={projectOffset===0} onClick={()=>setProjectOffset(Math.max(0,projectOffset-25))} style={{...button,background:'#edf3f9',color:'#173f72'}}>Sebelumnya</button><button type="button" disabled={projectOffset+25>=projectTotal} onClick={()=>setProjectOffset(projectOffset+25)} style={button}>Berikutnya</button></div></div>
      {projectDetail&&<div style={{marginTop:16,padding:14,background:'#f7f9fc',borderRadius:12}}><div style={{display:'flex',justifyContent:'space-between',gap:8}}><strong>Project detail</strong><button type="button" onClick={()=>setProjectDetail(null)} style={{border:0,background:'transparent',color:'#47719e',cursor:'pointer'}}>Tutup</button></div><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere',fontSize:12,color:'#43536a'}}>{JSON.stringify(projectDetail,null,2)}</pre></div>}
      {editingProject&&<form onSubmit={saveProject} style={{display:'grid',gap:8,padding:14,background:'#f7f9fc',borderRadius:12,marginTop:16}}><strong>Edit project · {editingProject.name}</strong><input aria-label="Edit nama project" value={editName} onChange={e=>setEditName(e.target.value)} required style={field}/><textarea aria-label="Edit deskripsi project" value={editDescription} onChange={e=>setEditDescription(e.target.value)} rows={3} style={field}/><div style={{display:'flex',gap:8}}><button disabled={busy} style={button}>Simpan perubahan</button><button type="button" onClick={()=>setEditingProject(null)} style={{...button,background:'#edf3f9',color:'#173f72'}}>Batal</button></div></form>}

    </section>
  </main>;
}
