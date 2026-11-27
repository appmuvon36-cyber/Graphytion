-- Durable image/video generation lifecycle using the existing Media Worker.
begin;

alter table public.project_assets
  drop constraint if exists project_assets_size_bytes_check;
alter table public.project_assets
  add constraint project_assets_size_bytes_check
  check (size_bytes > 0 and size_bytes <= 536870912);
update storage.buckets set file_size_limit=536870912
  where id='project-assets';

create table if not exists public.media_generation_jobs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  project_id uuid not null references public.video_projects(id) on delete cascade,
  requested_by uuid not null references auth.users(id) on delete restrict,
  media_type text not null check (media_type in ('image','video')),
  provider_key text not null check (provider_key in ('gemini')),
  model_key text not null check (char_length(model_key) between 1 and 128),
  prompt text not null check (char_length(prompt) between 1 and 32000),
  generation_config jsonb not null default '{}'::jsonb,
  status text not null default 'queued' check (status in (
    'queued','processing','cancel_requested','completed','failed','cancelled'
  )),
  error_code text,
  attempt_count integer not null default 0 check (attempt_count >= 0),
  max_attempts integer not null default 3 check (max_attempts between 1 and 5),
  worker_id text,
  lease_expires_at timestamptz,
  provider_job_id text,
  provider_provenance jsonb not null default '{}'::jsonb,
  provider_usage jsonb,
  provider_cost_microusd bigint check (provider_cost_microusd is null or provider_cost_microusd >= 0),
  provider_cost_status text not null default 'unpriced' check (provider_cost_status in ('priced','unpriced')),
  quota_reservation_id uuid references public.quota_reservations(id) on delete set null,
  asset_id uuid references public.project_assets(id) on delete set null,
  output_mime_type text,
  output_size_bytes bigint,
  output_sha256 text,
  idempotency_key text not null check (char_length(idempotency_key) between 16 and 128),
  created_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz,
  updated_at timestamptz not null default now(),
  unique(workspace_id,idempotency_key),
  check (
    (status='completed' and asset_id is not null and output_mime_type is not null
      and output_size_bytes is not null and output_sha256 is not null)
    or status<>'completed'
  )
);
create index if not exists media_generation_queue_idx
  on public.media_generation_jobs(status,created_at)
  where status in ('queued','processing','cancel_requested');
create index if not exists media_generation_project_history_idx
  on public.media_generation_jobs(project_id,created_at desc);
create index if not exists media_generation_workspace_history_idx
  on public.media_generation_jobs(workspace_id,created_at desc);

alter table public.media_generation_jobs enable row level security;
drop policy if exists media_generation_workspace_access on public.media_generation_jobs;
create policy media_generation_workspace_access on public.media_generation_jobs
  for all to graphytion_api
  using (private.graphytion_is_workspace_member(workspace_id))
  with check (private.graphytion_is_workspace_member(workspace_id));
drop policy if exists media_generation_platform_admin_read on public.media_generation_jobs;
create policy media_generation_platform_admin_read on public.media_generation_jobs
  for select to graphytion_api using (private.graphytion_is_platform_admin());

revoke all on public.media_generation_jobs from public,anon,authenticated,service_role;
grant select,insert,update on public.media_generation_jobs to graphytion_api;

create or replace function private.graphytion_claim_media_generation_job(
  p_worker_id text
) returns setof public.media_generation_jobs
language plpgsql security definer set search_path='' as $$$
declare claimed_id uuid;
begin
  if p_worker_id is null or length(p_worker_id)<1 or length(p_worker_id)>128 then
    raise exception using errcode='22023',message='MEDIA_WORKER_ID_INVALID';
  end if;
  select id into claimed_id from public.media_generation_jobs
    where status='queued' and attempt_count<max_attempts
    order by created_at for update skip locked limit 1;
  if claimed_id is null then return; end if;
  return query update public.media_generation_jobs
    set status='processing',worker_id=p_worker_id,
        lease_expires_at=now()+interval '5 minutes',
        attempt_count=attempt_count+1,started_at=coalesce(started_at,now()),updated_at=now()
    where id=claimed_id and status='queued'
    returning *;
end $$;

create or replace function private.graphytion_heartbeat_media_generation_job(
  p_job_id uuid,p_worker_id text
) returns boolean language sql security definer set search_path='' as $$$
  update public.media_generation_jobs set lease_expires_at=now()+interval '5 minutes',updated_at=now()
  where id=p_job_id and worker_id=p_worker_id and status='processing'
  returning true;
$$;

create or replace function private.graphytion_media_generation_owner(
  p_job_id uuid,p_worker_id text
) returns uuid language sql security definer set search_path='' as $$
  select requested_by from public.media_generation_jobs
  where id=p_job_id and worker_id=p_worker_id
$$;

create or replace function private.graphytion_media_generation_status(
  p_job_id uuid,p_worker_id text
) returns table(status text,requested_by uuid)
language sql security definer set search_path='' as $$
  select j.status,j.requested_by from public.media_generation_jobs j
  where j.id=p_job_id and j.worker_id=p_worker_id
$$;

create or replace function private.graphytion_recover_media_generation_jobs()
returns table(job_id uuid,job_status text)
language plpgsql security definer set search_path='' as $$
begin
  return query
  update public.media_generation_jobs j set
    status=case
      when j.status='cancel_requested' then 'cancelled'
      when j.attempt_count>=j.max_attempts then 'failed'
      else 'queued'
    end,
    error_code=case
      when j.status='cancel_requested' then 'CANCELLED_AFTER_WORKER_LEASE_EXPIRED'
      when j.attempt_count>=j.max_attempts then 'MEDIA_WORKER_LETRIES_EXHAUSTED'
      else 'MEDIA_WORKER_LEASE_EXPIRED'
    end,
    worker_id=null,lease_expires_at=null,
    completed_at=case when j.status='cancel_requested' or j.attempt_count>=j.max_attempts then now() else null end,
    updated_at=now()
  where j.status in ('processing','cancel_requested')
    and j.lease_expires_at < now()
  returning j.id,j.status;
end $;

revoke all on function private.graphytion_claim_media_generation_job(text) from public,anon,authenticated,service_role;
revoke all on function private.graphytion_heartbeat_media_generation_job(uuid,text) from public,anon,authenticated,service_role;
revoke all on function private.graphytion_media_generation_owner(uuid,text) from public,anon,authenticated,service_role;
revoke all on function private.graphytion_media_generation_status(uuid,text) from public,anon,authenticated,service_role;
revoke all on function private.graphytion_recover_media_generation_jobs() from public,anon,authenticated,service_role;
grant execute on function private.graphytion_claim_media_generation_job(text) to graphytion_api;
grant execute on function private.graphytion_heartbeat_media_generation_job(uuid,text) to graphytion_api;
grant execute on function private.graphytion_media_generation_owner(uuid,text) to graphytion_api;
grant execute on function private.graphytion_media_generation_status(uuid,text) to graphytion_api;
grant execute on function private.graphytion_recover_media_generation_jobs() to graphytion_api;

commit;
