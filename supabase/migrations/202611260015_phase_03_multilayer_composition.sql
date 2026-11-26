-- Phase 03: versioned multi-layer composition, profiles, component governance and media metadata.
begin;

create table if not exists public.video_timelines (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  project_id uuid not null references public.video_projects(id) on delete cascade,
  version integer not null check (version > 0),
  schema_version integer not null default 2 check (schema_version = 2),
  fps integer not null check (fps between 1 and 120),
  width integer not null check (width between 320 and 7680),
  height integer not null check (height between 240 and 4320),
  duration_frames integer not null check (duration_frames between 1 and 216000),
  snapshot jsonb not null,
  compiled_hash text not null check (compiled_hash ~ '^[a-f0-9]{64}$'),
  created_by uuid not null references public.profiles(id),
  created_at timestamptz not null default now(),
  unique (project_id, version),
  unique (id, project_id, workspace_id)
);
create index if not exists video_timelines_project_version_idx on public.video_timelines(project_id, version desc);
alter table public.video_timelines enable row level security;
drop policy if exists video_timelines_tenant_api on public.video_timelines;
create policy video_timelines_tenant_api on public.video_timelines for all to graphytion_api
  using (private.graphytion_is_workspace_member(workspace_id))
  with check (private.graphytion_is_workspace_member(workspace_id));
revoke all on public.video_timelines from public, anon, authenticated, service_role;
grant select, insert, update, delete on public.video_timelines to graphytion_api;

create table if not exists public.render_profiles (
  id uuid primary key default gen_random_uuid(),
  profile_key text not null,
  name text not null,
  description text,
  scope text not null default 'global' check (scope in ('global','workspace','project')),
  workspace_id uuid references public.workspaces(id) on delete cascade,
  project_id uuid references public.video_projects(id) on delete cascade,
  version integer not null default 1 check (version > 0),
  width integer not null check (width between 320 and 7680),
  height integer not null check (height between 240 and 4320),
  fps integer not null check (fps between 1 and 120),
  container text not null check (container in ('mp4','webm')),
  video_codec text not null check (video_codec in ('h264','h265','vp8','vp9')),
  video_crf integer not null check (video_crf between 0 and 51),
  video_bitrate text,
  audio_codec text not null check (audio_codec in ('aac','opus','none')),
  audio_bitrate text,
  render_concurrency integer not null default 2 check (render_concurrency between 1 and 8),
  priority integer not null default 10 check (priority between 0 and 100),
  thumbnail_enabled boolean not null default true,
  preview_enabled boolean not null default true,
  is_default boolean not null default false,
  is_archived boolean not null default false,
  created_by uuid references public.profiles(id),
  updated_by uuid references public.profiles(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (profile_key, scope, version),
  check (
    (scope='global' and workspace_id is null and project_id is null) or
    (scope='workspace' and workspace_id is not null and project_id is null) or
    (scope='project' and project_id is not null)
  ),
  check (
    (container='mp4' and video_codec in ('h264','h265') and audio_codec in ('aac','none')) or
    (container='webm' and video_codec in ('vp8','vp9') and audio_codec in ('opus','none'))
  )
);
create index if not exists render_profiles_active_idx on public.render_profiles(scope, is_default, priority desc) where is_archived=false;
alter table public.render_profiles enable row level security;
drop policy if exists render_profiles_admin_api on public.render_profiles;
create policy render_profiles_admin_api on public.render_profiles for all to graphytion_api
  using (private.graphytion_is_platform_admin()) with check (private.graphytion_is_platform_admin());
drop policy if exists render_profiles_active_read on public.render_profiles;
create policy render_profiles_active_read on public.render_profiles for select to graphytion_api
  using (scope='global' and is_archived=false);
revoke all on public.render_profiles from public, anon, authenticated, service_role;
grant select, insert, update, delete on public.render_profiles to graphytion_api;

insert into public.render_profiles(profile_key,name,description,width,height,fps,container,video_codec,video_crf,audio_codec,audio_bitrate,render_concurrency,priority,is_default)
values
 ('draft-preview','Draft Preview','Fast preview output',1280,720,30,'mp4','h264',28,'aac','128k',2,5,false),
 ('standard','Standard','Balanced quality and render cost',1920,1080,30,'mp4','h264',23,'aac','192k',2,10,true),
 ('high-quality','High Quality','High quality 1080p output',1920,1080,30,'mp4','h264',18,'aac','256k',2,20,false),
 ('full-hd','Full HD','Full HD 30 FPS delivery',1920,1080,30,'mp4','h264',20,'aac','192k',2,15,false),
 ('4k','4K','Ultra HD delivery',3840,2160,30,'mp4','h265',20,'aac','256k',1,30,false)
on conflict (profile_key, scope, version) do nothing;

alter table public.render_jobs add column if not exists timeline_id uuid;
alter table public.render_jobs add column if not exists snapshot_version integer not null default 1;
alter table public.render_jobs add column if not exists asset_manifest jsonb not null default '[]'::jsonb;
alter table public.render_jobs add column if not exists render_profile_id uuid references public.render_profiles(id);
create index if not exists render_jobs_timeline_idx on public.render_jobs(timeline_id) where timeline_id is not null;

create table if not exists public.render_attempts (
  id uuid primary key default gen_random_uuid(),
  render_job_id uuid not null references public.render_jobs(id) on delete cascade,
  attempt_number integer not null check (attempt_number > 0),
  worker_id text,
  status text not null check (status in ('claimed','rendering','uploading','completed','failed','cancelled')),
  error_code text,
  diagnostics jsonb not null default '{}'::jsonb,
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  unique (render_job_id, attempt_number)
);
alter table public.render_attempts enable row level security;
drop policy if exists render_attempts_tenant_api on public.render_attempts;
create policy render_attempts_tenant_api on public.render_attempts for all to graphytion_api
  using (exists(select 1 from public.render_jobs r where r.id=render_job_id and private.graphytion_is_workspace_member(r.workspace_id)))
  with check (exists(select 1 from public.render_jobs r where r.id=render_job_id and private.graphytion_is_workspace_member(r.workspace_id)));
revoke all on public.render_attempts from public, anon, authenticated, service_role;
grant select, insert, update, delete on public.render_attempts to graphytion_api;

create table if not exists public.motion_component_controls (
  component_key text primary key,
  component_version text not null,
  category text not null check (category in ('image','video','shape','typography','chart','audio','subtitle')),
  enabled boolean not null default true,
  reason text,
  updated_by uuid references public.profiles(id),
  updated_at timestamptz not null default now()
);
insert into public.motion_component_controls(component_key,component_version,category,enabled) values
 ('core.title-card.v1','1.1.0','typography',true),
 ('visual.image.v1','1.0.0','image',true),
 ('visual.video.v1','1.0.0','video',true),
 ('visual.shape.v1','1.0.0','shape',true),
 ('text.basic.v1','1.0.0','typography',true),
 ('data.chart.v1','1.0.0','chart',true),
 ('audio.clip.v1','1.0.0','audio',true),
 ('text.subtitle.v1','1.0.0','subtitle',true)
on conflict (component_key) do nothing;
alter table public.motion_component_controls enable row level security;
drop policy if exists motion_components_admin_api on public.motion_component_controls;
create policy motion_components_admin_api on public.motion_component_controls for all to graphytion_api
  using (private.graphytion_is_platform_admin()) with check (private.graphytion_is_platform_admin());
drop policy if exists motion_components_enabled_read on public.motion_component_controls;
create policy motion_components_enabled_read on public.motion_component_controls for select to graphytion_api using (enabled=true);
revoke all on public.motion_component_controls from public, anon, authenticated, service_role;
grant select, insert, update, delete on public.motion_component_controls to graphytion_api;

create table if not exists public.subtitle_tracks (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  project_id uuid not null references public.video_projects(id) on delete cascade,
  timeline_id uuid references public.video_timelines(id) on delete set null,
  language text not null default 'id-ID',
  format text not null default 'webvtt' check (format in ('webvtt','srt')),
  version integer not null default 1 check (version > 0),
  style_config jsonb not null default '{}'::jsonb,
  created_by uuid not null references public.profiles(id),
  created_at timestamptz not null default now()
);
create table if not exists public.subtitle_segments (
  id uuid primary key default gen_random_uuid(),
  track_id uuid not null references public.subtitle_tracks(id) on delete cascade,
  segment_index integer not null check (segment_index >= 0),
  start_ms integer not null check (start_ms >= 0),
  end_ms integer not null check (end_ms > start_ms),
  text text not null check (char_length(text) between 1 and 4000),
  speaker text,
  word_timings jsonb not null default '[]'::jsonb,
  unique (track_id, segment_index)
);
alter table public.subtitle_tracks enable row level security;
alter table public.subtitle_segments enable row level security;
drop policy if exists subtitle_tracks_tenant_api on public.subtitle_tracks;
create policy subtitle_tracks_tenant_api on public.subtitle_tracks for all to graphytion_api
  using (private.graphytion_is_workspace_member(workspace_id)) with check (private.graphytion_is_workspace_member(workspace_id));
drop policy if exists subtitle_segments_tenant_api on public.subtitle_segments;
create policy subtitle_segments_tenant_api on public.subtitle_segments for all to graphytion_api
  using (exists(select 1 from public.subtitle_tracks t where t.id=track_id and private.graphytion_is_workspace_member(t.workspace_id)))
  with check (exists(select 1 from public.subtitle_tracks t where t.id=track_id and private.graphytion_is_workspace_member(t.workspace_id)));
revoke all on public.subtitle_tracks, public.subtitle_segments from public, anon, authenticated, service_role;
grant select, insert, update, delete on public.subtitle_tracks, public.subtitle_segments to graphytion_api;

create table if not exists public.audio_generations (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  project_id uuid not null references public.video_projects(id) on delete cascade,
  scene_id uuid references public.storyboard_scenes(id) on delete set null,
  requested_by uuid not null references public.profiles(id),
  provider_key text not null,
  model_key text not null,
  voice_key text not null,
  input_text text not null check (char_length(input_text) between 1 and 20000),
  language text not null default 'id-ID',
  generation_config jsonb not null default '{}'::jsonb,
  status text not null check (status in ('queued','running','completed','failed','provider_unavailable','cancelled')),
  worker_id text,
  lease_expires_at timestamptz,
  attempt_count integer not null default 0 check (attempt_count >= 0),
  max_attempts integer not null default 3 check (max_attempts between 1 and 10),
  idempotency_key text,
  asset_id uuid references public.project_assets(id) on delete set null,
  error_code text,
  created_at timestamptz not null default now(),
  completed_at timestamptz
);
create index if not exists audio_generations_project_idx on public.audio_generations(project_id,created_at desc);
create unique index if not exists audio_generations_idempotency_idx on public.audio_generations(workspace_id,idempotency_key) where idempotency_key is not null;
create index if not exists audio_generations_recovery_idx on public.audio_generations(status,lease_expires_at,created_at) where status in ('queued','running');
alter table public.audio_generations enable row level security;
drop policy if exists audio_generations_tenant_api on public.audio_generations;
create policy audio_generations_tenant_api on public.audio_generations for all to graphytion_api
  using (private.graphytion_is_workspace_member(workspace_id)) with check (private.graphytion_is_workspace_member(workspace_id));
revoke all on public.audio_generations from public, anon, authenticated, service_role;
grant select, insert, update, delete on public.audio_generations to graphytion_api;

create or replace function private.graphytion_claim_render_job(
  p_worker_id text, p_job_id uuid default null, p_lease_seconds integer default 300
)
returns setof public.render_jobs language plpgsql security definer set search_path=''
as $$
begin
  if p_worker_id is null or char_length(p_worker_id) not between 1 and 128 then raise exception 'invalid worker identity'; end if;
  if p_lease_seconds < 60 or p_lease_seconds > 1800 then raise exception 'invalid lease duration'; end if;
  return query with candidate as (
    select r.id from public.render_jobs r
    where (p_job_id is null or r.id=p_job_id) and r.attempt_count<r.max_attempts
      and (r.status='queued' or (r.status='rendering' and (r.lease_expires_at is null or r.lease_expires_at<now())))
    order by coalesce((r.render_config->>'priority')::integer,0) desc,r.created_at
    for update skip locked limit 1
  )
  update public.render_jobs r set status='rendering',worker_id=p_worker_id,
    lease_expires_at=now()+make_interval(secs=>p_lease_seconds),
    attempt_count=r.attempt_count+1,started_at=coalesce(r.started_at,now())
  from candidate c where r.id=c.id returning r.*;
end;
$$;

create or replace function private.graphytion_claim_audio_generation(p_worker_id text,p_job_id uuid default null)
returns setof public.audio_generations language plpgsql security definer set search_path=''
as $$
begin
  if p_worker_id is null or char_length(p_worker_id) not between 1 and 128 then raise exception 'invalid worker identity'; end if;
  return query with candidate as (
    select a.id from public.audio_generations a
    where (p_job_id is null or a.id=p_job_id) and a.attempt_count<a.max_attempts
      and (a.status='queued' or (a.status='running' and a.lease_expires_at<now()))
    order by a.created_at for update skip locked limit 1
  )
  update public.audio_generations a set status='running',worker_id=p_worker_id,
    lease_expires_at=now()+interval '5 minutes',attempt_count=a.attempt_count+1
  from candidate c where a.id=c.id returning a.*;
end;
$$;
create or replace function private.graphytion_media_job_owner(p_job_id uuid,p_worker_id text)
returns uuid language sql security definer set search_path=''
as $$ select requested_by from public.audio_generations where id=p_job_id and worker_id=p_worker_id and status='running' $$;
create or replace function private.graphytion_heartbeat_media_job(p_job_id uuid,p_worker_id text)
returns uuid language sql security definer set search_path=''
as $$ update public.audio_generations set lease_expires_at=now()+interval '5 minutes' where id=p_job_id and worker_id=p_worker_id and status='running' returning requested_by $$;
create or replace function private.graphytion_recover_audio_generations()
returns setof uuid language sql security definer set search_path=''
as $$ update public.audio_generations set status='queued',worker_id=null,lease_expires_at=null where status='running' and lease_expires_at<now() and attempt_count<max_attempts returning id $$;

revoke all on function private.graphytion_claim_render_job(text,uuid,integer) from public,anon,authenticated,service_role;
revoke all on function private.graphytion_claim_audio_generation(text,uuid) from public,anon,authenticated,service_role;
revoke all on function private.graphytion_media_job_owner(uuid,text) from public,anon,authenticated,service_role;
revoke all on function private.graphytion_heartbeat_media_job(uuid,text) from public,anon,authenticated,service_role;
revoke all on function private.graphytion_recover_audio_generations() from public,anon,authenticated,service_role;
grant execute on function private.graphytion_claim_render_job(text,uuid,integer) to graphytion_api;
grant execute on function private.graphytion_claim_audio_generation(text,uuid) to graphytion_api;
grant execute on function private.graphytion_media_job_owner(uuid,text) to graphytion_api;
grant execute on function private.graphytion_heartbeat_media_job(uuid,text) to graphytion_api;
grant execute on function private.graphytion_recover_audio_generations() to graphytion_api;

commit;
