'use client';

import {useEffect,useMemo,useState} from 'react';
import {createApiClient} from '@graphytion/api-client';
import type {CompositionSnapshot,ResolvedCompositionAssets} from '@graphytion/motion-components';

type TemplateItem={id:string;name:string;category:string;version:number};
type BrandKitItem={id:string;name:string;version:number;brand_config:Record<string,unknown>};
const field:React.CSSProperties={width:'100%',padding:'9px 11px',border:'1px solid #dce3ed',borderRadius:8,fontSize:13};
const button:React.CSSProperties={border:0,borderRadius:8,padding:'9px 12px',background:'#173f72',color:'#fff',fontWeight:700,cursor:'pointer'};

export function TemplateBrandPanel({projectId,onApplied}:{projectId:string;onApplied:(snapshot:CompositionSnapshot,assets:ResolvedCompositionAssets,version:number)=>void}){
 const api=useMemo(()=>createApiClient({baseUrl:typeof window!=='undefined'?window.location.origin+'/api':'http://localhost:3000/api'}),[]);
 const [templates,setTemplates]=useState<TemplateItem[]>([]);
 const [kits,setKits]=useState<BrandKitItem[]>([]);
 const [templateName,setTemplateName]=useState('');
 const [templateCategory,setTemplateCategory]=useState('motion-graphic');
 const [kitName,setKitName]=useState('');
 const [kitConfig,setKitConfig]=useState('{"colors":{"primary":"#173F72","secondary":"#56B8E8","accent":"#1769C2","background":"#FFFFFF","text":"#142033","surface":"#F3F6FA"},"typography":{"font_family":"Inter","heading_font_family":"Inter","body_font_family":"Inter","font_weight":"600"}}');
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState('');
 const [notice,setNotice]=useState('');
 async function request<T>(path:string,init:RequestInit={}):Promise<T>{return api.request<T>(path,init);}
 async function load(){try{const [t,b]=await Promise.all([request<{data:TemplateItem[]}>('/projects/'+projectId+'/templates'),request<{data:BrandKitItem[]}>('/projects/'+projectId+'/brand-kits')]);setTemplates(t.data);setKits(b.data);}catch(e){setError(e instanceof Error?e.message:'Template dan Brand Kit tidak dapat dimuat');}}
 useEffect(()=>{void load();},[projectId]);
 async function createTemplate(e:React.FormEvent){e.preventDefault();setBusy(true);setError('');setNotice('');try{await request('/projects/'+projectId+'/templates',{method:'POST',body:JSON.stringify({name:templateName,category:templateCategory})});setTemplateName('');setNotice('Template tersimpan dari timeline terakhir.');await load();}catch(e){setError(e instanceof Error?e.message:'Gagal menyimpan template');}finally{setBusy(false);}}
 async function applyTemplate(id:string){setBusy(true);setError('');try{const result=await request<{data:{snapshot:CompositionSnapshot;version:number}}>('/projects/'+projectId+'/templates/'+id+'/apply',{method:'POST'});onApplied(result.data.snapshot,{},result.data.version);setNotice('Template diterapkan sebagai timeline version '+result.data.version+'.');}catch(e){setError(e instanceof Error?e.message:'Template gagal diterapkan');}finally{setBusy(false);}}
 async function createKit(e:React.FormEvent){e.preventDefault();setBusy(true);setError('');setNotice('');try{const config=JSON.parse(kitConfig);await request('/projects/'+projectId+'/brand-kits',{method:'POST',body:JSON.stringify({name:kitName,config})});setKitName('');setNotice('Brand Kit tersimpan.');await load();}catch(e){setError(e instanceof Error?e.message:'Brand Kit tidak valid atau gagal disimpan');}finally{setBusy(false);}}
 async function applyKit(id:string){setBusy(true);setError('');try{await request('/projects/'+projectId+'/brand-kits/'+id+'/apply',{method:'PUT'});setNotice('Brand Kit diterapkan ke project. Simpan timeline agar token brand diterapkan ke composition.');}catch(e){setError(e instanceof Error?e.message:'Brand Kit gagal diterapkan');}finally{setBusy(false);}}
 return <section style={{border:'1px solid #e5eaf1',borderRadius:14,padding:18,marginBottom:14,background:'#fff'}}>
  <h2 style={{marginTop:0}}>Templates & Brand Kit</h2>
  {error&&<p role="alert" style={{color:'#b42318'}}>{error}</p>}{notice&&<p role="status" style={{color:'#176b45'}}>{notice}</p>}
  <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(250px,1fr))',gap:18}}>
   <div><h3 style={{marginTop:0}}>Reusable composition templates</h3><form onSubmit={createTemplate} style={{display:'grid',gap:8}}><input aria-label="Template name" required value={templateName} onChange={e=>setTemplateName(e.target.value)} placeholder="Template name" style={field}/><input aria-label="Template category" required value={templateCategory} onChange={e=>setTemplateCategory(e.target.value)} placeholder="Category" style={field}/><button disabled={busy||!templateName.trim()} style={button}>Save current timeline as template</button></form>
    {templates.map(t=><div key={t.id} style={{display:'flex',justifyContent:'space-between',gap:8,alignItems:'center',padding:'8px 0',borderTop:'1px solid #edf0f5'}}><span><strong>{t.name}</strong><small style={{display:'block',color:'#68788e'}}>{t.category} · v{t.version}</small></span><button type="button" disabled={busy} onClick={()=>void applyTemplate(t.id)} style={button}>Apply</button></div>)}
    {!templates.length&&<p style={{fontSize:12,color:'#68788e'}}>Belum ada template workspace.</p>}
   </div>
   <div><h3 style={{marginTop:0}}>Workspace Brand Kits</h3><form onSubmit={createKit} style={{display:'grid',gap:8}}><input aria-label="Brand Kit name" required value={kitName} onChange={e=>setKitName(e.target.value)} placeholder="Brand Kit name" style={field}/><textarea aria-label="Brand Kit JSON" rows={7} value={kitConfig} onChange={e=>setKitConfig(e.target.value)} style={{...field,fontFamily:'monospace',fontSize:11}}/><button disabled={busy||!kitName.trim()} style={button}>Save Brand Kit</button></form>
    {kits.map(k=><div key={k.id} style={{display:'flex',justifyContent:'space-between',gap:8,alignItems:'center',padding:'8px 0',borderTop:'1px solid #edf0f5'}}><span><strong>{k.name}</strong><small style={{display:'block',color:'#68788e'}}>v{k.version}</small></span><button type="button" disabled={busy} onClick={()=>void applyKit(k.id)} style={button}>Apply to project</button></div>)}
    {!kits.length&&<p style={{fontSize:12,color:'#68788e'}}>Belum ada Brand Kit.</p>}
   </div>
  </div>
 </section>;
}
