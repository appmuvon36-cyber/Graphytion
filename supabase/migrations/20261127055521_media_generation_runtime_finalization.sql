-- Graphytion media generation: one production-safe consolidation migration.
-- Replaces the unapplied 22409-22414 media migration series. No pricing table is created.
begin;

create table if not exists public.media_generation_jobs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  project_id uuid not null references public.video_projects(id) on delete cascade,
  requested_by uuid not null references auth.users(id) on delete restrict,
  media_type text not null check (media_type in ('image','video')),
  provider_key text not null default 'gemini' check (provider_key in ('gemini')),
  model_key text not null check (char_length(model_key) between 1 and 128),
  prompt text not null check (char_length(prompt) between 1 and 32000),
  generation_config jsonb not null default '{}'::jsonb,
  status text not null default 'queued' check (status in ('queued','processing','cancel_requested','completed','failed','cancelled')),
  error_code text,
  attempt_count integer not null default 0 check (attempt_count >= 0),
  max_attempts integer not null default 3 check (max_attempts between 1 and 5),
  retry_count integer not null default 0 check (retry_count >= 0),
  max_retries integer not null default 3 check (max_retries between 0 and 5),
  next_retry_at timestamptz,
  last_error text,
  last_error_class text check (last_error_class is null or last_error_class in ('transient','permanent','configuration','unknown','permanent_or_exhausted')),
  worker_id text,
  lease_expires_at timestamptz,
  provider_job_id text,
  provider_operation_status text not null default 'not_started'
    check (provider_operation_status in ('not_started','submitted','queued','in_progress','completed','failed','cancelled','unknown')),
  provider_operation_last_polled_at timestamptz,
  provider_operation_poll_count integer not null default 0 check (provider_operation_poll_count >= 0),
  provider_operation_history jsonb not null default '[]'::jsonb,
  provider_provenance jsonb not null default '{}'::jsonb,
  provider_usage jsonb,
  estimated_provider_cost_microusd bigint check (estimated_provider_cost_microusd is null or estimated_provider_cost_microusd >= 0),
  provider_cost_microusd bigint check (provider_cost_microusd is null or provider_cost_microusd >= 0),
  provider_cost_status text not null default 'unpriced' check (provider_cost_status in ('priced','unpriced')),
  operational_cost_microusd bigint check (operational_cost_microusd is null or operational_cost_microusd >= 0),
  quota_debit_microusd bigint check (quota_debit_microusd is null or quota_debit_microusd >= 0),
  margin_microusd bigint,
  economics_status text not null default 'unpriced' check (economics_status in ('complete','partial','unpriced')),
  quota_reconciliation_status text not null default 'pending' check (quota_reconciliation_status in ('pending','complete','reversed','not_required','failed')),
  quota_reconciled_at timestamptz,
  quota_reservation_id uuid references public.quota_reservations(id) on delete set null,
  quota_price_id uuid references public.quota_operation_prices(id) on delete set null,
  operational_price_id uuid references public.quota_operation_prices(id) on delete set null,
  provider_price_id uuid references public.ai_model_prices(id) on delete set null,
  reversal_reference text,
  currency text not null default 'USD' check (currency ~ '^[A-Z]{3}$'),
  price_snapshot jsonb not null default '{}'::jsonb,
  asset_id uuid references public.project_assets(id) on delete set null,
  output_mime_type text,
  output_size_bytes bigint check (output_size_bytes is null or output_size_bytes > 0),
  output_sha256 text check (output_sha256 is null or output_sha256 ~ '^[a-f0-9]{64}$'),
  idempotency_key text not null check (char_length(idempotency_key) between 16 and 128),
  created_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz,
  updated_at timestamptz not null default now(),
  unique(workspace_id,idempotency_key),
  check ((status='completed' and asset_id is not null and output_mime_type is not null
    and output_size_bytes is not null and output_sha256 is not null) or status<>'completed')
);

alter table public.quota_operation_prices
  add column if not exists price_kind text not null default 'quota',
  add column if not exists media_type text,
  add column if not exists provider_key text,
  add column if not exists model_key text;
alter table public.quota_operation_prices
  drop constraint if exists quota_operation_prices_operation_key_effective_at_key;
drop index if exists public.quota_operation_prices_operation_key_effective_at_key;
alter table public.quota_operation_prices
  drop constraint if exists quota_operation_prices_price_kind_check,
  drop constraint if exists quota_operation_prices_media_type_check,
  drop constraint if exists quota_operation_prices_operational_scope_check;
alter table public.quota_operation_prices
  add constraint quota_operation_prices_price_kind_check check (price_kind in ('quota','operational')),
  add constraint quota_operation_prices_media_type_check check (media_type is null or media_type in ('image','video')),
  add constraint quota_operation_prices_operational_scope_check check (
    (price_kind='quota' and media_type is null and provider_key is null and model_key is null)
    or (price_kind='operational' and media_type is not null and provider_key is not null and model_key is not null
      and ((media_type='image' and operation_key='image_generation') or (media_type='video' and operation_key='video_generation')))
  );
create unique index if not exists quota_operation_prices_quota_history_uq
  on public.quota_operation_prices(operation_key,effective_at) where price_kind='quota';
create unique index if not exists quota_operation_prices_operational_history_uq
  on public.quota_operation_prices(operation_key,media_type,provider_key,model_key,effective_at)
  where price_kind='operational';
create index if not exists quota_operation_prices_operational_lookup_idx
  on public.quota_operation_prices(media_type,provider_key,model_key,effective_at desc)
  where price_kind='operational' and is_active=true;

alter table public.project_assets
  drop constraint if exists project_assets_size_bytes_check;
alter table public.project_assets
  add constraint project_assets_size_bytes_check check (size_bytes > 0 and size_bytes <= 536870912),
  add column if not exists asset_family_id uuid not null default gen_random_uuid(),
  add column if not exists version_number integer not null default 1 check (version_number > 0),
  add column if not exists supersedes_asset_id uuid references public.project_assets(id) on delete set null,
  add column if not exists source_type text not null default 'upload'
    check (source_type in ('upload','generated','external','stock','system')),
  add column if not exists source_provider text,
  add column if not exists source_model text,
  add column if not exists source_job_id uuid references public.media_generation_jobs(id) on delete set null,
  add column if not exists provenance jsonb not null default '{}'::jsonb,
  add column if not exists generation_metadata jsonb not null default '{}'::jsonb,
  add column if not exists usage_rights_status text not null default 'unverified'
    check (usage_rights_status in ('unverified','verified','restricted','expired')),
  add column if not exists license_type text,
  add column if not exists commercial_use_allowed boolean,
  add column if not exists attribution text,
  add column if not exists generated_at timestamptz;
create unique index if not exists project_assets_family_version_uq
  on public.project_assets(asset_family_id,version_number);
create index if not exists project_assets_workspace_library_idx
  on public.project_assets(workspace_id,status,created_at desc) where status='active';
create index if not exists project_assets_source_job_idx
  on public.project_assets(source_job_id) where source_job_id is not null;

update storage.buckets set file_size_limit=536870912 where id='project-assets';

create index if not exists media_generation_queue_due_idx
  on public.media_generation_jobs(status,next_retry_at,created_at)
  where status='queued';
create index if not exists media_generation_lease_idx
  on public.media_generation_jobs(lease_expires_at)
  where status in ('processing','cancel_requested');
create index if not exists media_generation_project_history_idx
  on public.media_generation_jobs(project_id,created_at desc);
create index if not exists media_generation_workspace_history_idx
  on public.media_generation_jobs(workspace_id,created_at desc);
create unique index if not exists media_generation_provider_operation_uq
  on public.media_generation_jobs(provider_key,provider_job_id)
  where provider_job_id is not null;

alter table public.media_generation_jobs enable row level security;
drop policy if exists media_generation_workspace_access on public.media_generation_jobs;
create policy media_generation_workspace_access on public.media_generation_jobs
  for all to graphytion_api
  using (private.graphytion_is_workspace_member(workspace_id))
  with check (private.graphytion_is_workspace_member(workspace_id));
drop policy if exists media_generation_platform_admin_read on public.media_generation_jobs;
create policy media_generation_platform_admin_read on public.media_generation_jobs
  for select to graphytion_api using (private.graphytion_is_platform_admin());

drop policy if exists quota_operation_prices_api_read on public.quota_operation_prices;
create policy quota_operation_prices_api_read on public.quota_operation_prices
  for select to graphytion_api using (true);

create or replace function private.graphytion_claim_media_generation_job(p_worker_id text)
returns setof public.media_generation_jobs
language plpgsql security definer set search_path='' as $$
declare claimed_id uuid;
begin
  if p_worker_id is null or length(p_worker_id)<1 or length(p_worker_id)>128 then
    raise exception using errcode='22023',message='MEDIA_WORKER_ID_INVALID';
  end if;
  select id into claimed_id from public.media_generation_jobs
    where status='queued'
      and (attempt_count<max_attempts or (provider_job_id is not null and provider_operation_status in ('submitted','queued','in_progress','unknown')))
      and (retry_count<=max_retries or (provider_job_id is not null and provider_operation_status in ('submitted','queued','in_progress','unknown')))
      and (next_retry_at is null or next_retry_at<=now())
    order by coalesce(next_retry_at,created_at),created_at
    for update skip locked limit 1;
  if claimed_id is null then return; end if;
  return query update public.media_generation_jobs
    set status='processing',worker_id=p_worker_id,lease_expires_at=now()+interval '5 minutes',
        attempt_count=attempt_count+1,started_at=coalesce(started_at,now()),
        next_retry_at=null,updated_at=now()
    where id=claimed_id and status='queued'
    returning *;
end $$;

create or replace function private.graphytion_heartbeat_media_generation_job(p_job_id uuid,p_worker_id text)
returns boolean language sql security definer set search_path='' as $$
  update public.media_generation_jobs set lease_expires_at=now()+interval '5 minutes',updated_at=now()
  where id=p_job_id and worker_id=p_worker_id and status='processing'
  returning true;
$$;

create or replace function private.graphytion_media_generation_owner(p_job_id uuid,p_worker_id text)
returns uuid language sql security definer set search_path='' as $$
  select requested_by from public.media_generation_jobs where id=p_job_id and worker_id=p_worker_id
$$;

create or replace function private.graphytion_media_generation_status(p_job_id uuid,p_worker_id text)
returns table(status text,requested_by uuid)
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
      when (j.attempt_count>=j.max_attempts or j.retry_count>=j.max_retries)
        and not (j.provider_job_id is not null and j.provider_operation_status in ('submitted','queued','in_progress','unknown')) then 'failed'
      else 'queued'
    end,
    error_code=case
      when j.status='cancel_requested' then 'CANCELLED_AFTER_WORKER_LEASE_EXPIRED'
      when (j.attempt_count>=j.max_attempts or j.retry_count>=j.max_retries)
        and not (j.provider_job_id is not null and j.provider_operation_status in ('submitted','queued','in_progress','unknown')) then 'MEDIA_WORKER_RETRIES_EXHAUSTED'
      else 'MEDIA_WORKER_LEASE_EXPIRED'
    end,
    last_error=case when j.status='cancel_requested' then 'Provider outcome may still be billable after cancellation' else 'Worker lease expired; recovering durable job' end,
    last_error_class=case when j.status='cancel_requested' then 'unknown' else 'transient' end,
    retry_count=j.retry_count + case when j.status='processing' and j.provider_job_id is null
      and j.attempt_count<j.max_attempts and j.retry_count<j.max_retries then 1 else 0 end,
    next_retry_at=case
      when j.status='processing' and j.provider_job_id is not null
        and j.provider_operation_status in ('submitted','queued','in_progress','unknown') then now()
      when j.status='processing' and j.attempt_count<j.max_attempts and j.retry_count<j.max_retries
        then now()+make_interval(secs => least(300,(5*power(2,least(j.attempt_count,6)))::integer))
      else null end,
    worker_id=null,lease_expires_at=null,
    completed_at=case when j.status='cancel_requested'
      or ((j.attempt_count>=j.max_attempts or j.retry_count>=j.max_retries)
        and not (j.provider_job_id is not null and j.provider_operation_status in ('submitted','queued','in_progress','unknown'))) then now() else null end,
    updated_at=now()
  where j.status in ('processing','cancel_requested') and j.lease_expires_at<now()
  returning j.id,j.status;
end $$;

create or replace function private.graphytion_pending_media_reconciliation_jobs(p_limit integer default 50)
returns setof public.media_generation_jobs
language sql security definer set search_path='' as $$
  select j.* from public.media_generation_jobs j
  where j.status in ('completed','failed','cancelled') and j.economics_status in ('partial','unpriced')
  order by j.completed_at asc
  for update skip locked
  limit least(greatest(coalesce(p_limit,50),1),100)
$$;

revoke all on function private.graphytion_pending_media_reconciliation_jobs(integer) from public,anon,authenticated,service_role;
grant execute on function private.graphytion_pending_media_reconciliation_jobs(integer) to graphytion_api;

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

revoke all on public.media_generation_jobs from public,anon,authenticated,service_role;
grant select,insert,update on public.media_generation_jobs to graphytion_api;
grant select,insert,update on public.project_assets to graphytion_api;
grant select on public.quota_operation_prices to graphytion_api;

commit;
