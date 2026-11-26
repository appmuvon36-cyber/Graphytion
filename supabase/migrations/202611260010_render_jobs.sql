-- Render jobs persist immutable composition snapshots; Redis only signals workers.
begin;

insert into storage.buckets(id,name,public)
values ('render-artifacts','render-artifacts',false)
on conflict (id) do update set public=false;

create table if not exists public.render_jobs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  project_id uuid not null references public.video_projects(id) on delete cascade,
  requested_by uuid not null references public.profiles(id),
  status text not null default 'queued'
    check (status in ('queued','rendering','completed','failed','cancel_requested','cancelled')),
  composition_id text not null default 'GraphytionTimeline',
  composition_version text not null,
  timeline_snapshot jsonb not null,
  timeline_hash text not null check (timeline_hash ~ '^[a-f0-9]{64}$'),
  render_config jsonb not null default '{}'::jsonb,
  progress_percent numeric(5,2) not null default 0 check (progress_percent between 0 and 100),
  worker_id text,
  lease_expires_at timestamptz,
  attempt_count integer not null default 0 check (attempt_count >= 0),
  max_attempts integer not null default 3 check (max_attempts between 1 and 10),
  output_bucket text,
  output_path text,
  output_size_bytes bigint,
  output_sha256 text,
  error_code text,
  error_message_safe text,
  idempotency_key text not null check (char_length(idempotency_key) between 16 and 128),
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(workspace_id,idempotency_key)
);

create index if not exists render_jobs_project_created_idx
  on public.render_jobs(project_id,created_at desc);
create index if not exists render_jobs_worker_recovery_idx
  on public.render_jobs(status,lease_expires_at,created_at)
  where status in ('queued','rendering');

create trigger render_jobs_touch_updated_at
before update on public.render_jobs
for each row execute function public.graphytion_touch_updated_at();

alter table public.render_jobs enable row level security;
drop policy if exists render_jobs_api_tenant on public.render_jobs;
create policy render_jobs_api_tenant on public.render_jobs
  for all to graphytion_api
  using (private.graphytion_is_workspace_member(workspace_id))
  with check (private.graphytion_is_workspace_member(workspace_id));
drop policy if exists render_jobs_platform_admin_read on public.render_jobs;
create policy render_jobs_platform_admin_read on public.render_jobs
  for select to graphytion_api using (private.graphytion_is_platform_admin());

revoke all on public.render_jobs from public, anon, authenticated, service_role;
grant select,insert,update,delete on public.render_jobs to graphytion_api;

create or replace function private.graphytion_claim_render_job(
  p_worker_id text,
  p_job_id uuid default null,
  p_lease_seconds integer default 300
)
returns setof public.render_jobs
language plpgsql
security definer
set search_path = ''
as $$
begin
  if p_worker_id is null or char_length(p_worker_id) not between 1 and 128 then
    raise exception 'invalid worker identity';
  end if;
  if p_lease_seconds < 60 or p_lease_seconds > 1800 then
    raise exception 'invalid lease duration';
  end if;

  return query
  with candidate as (
    select r.id from public.render_jobs r
    where (p_job_id is null or r.id=p_job_id)
      and r.attempt_count < r.max_attempts
      and (
        r.status='queued'
        or (r.status='rendering' and (r.lease_expires_at is null or r.lease_expires_at<now()))
      )
    order by r.created_at
    for update skip locked
    limit 1
  )
  update public.render_jobs r
  set status='rendering',worker_id=p_worker_id,
      lease_expires_at=now()+make_interval(secs=>p_lease_seconds),
      attempt_count=r.attempt_count+1,started_at=coalesce(r.started_at,now())
  from candidate c
  where r.id=c.id
  returning r.*;
end;
$$;

revoke all on function private.graphytion_claim_render_job(text,uuid,integer)
  from public, anon, authenticated, service_role;
grant execute on function private.graphytion_claim_render_job(text,uuid,integer)
  to graphytion_api;

commit;
