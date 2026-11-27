-- Durable retry scheduling for creative runs.
-- PostgreSQL remains authoritative; workers must not rely on in-memory sleeps.
begin;

alter table public.production_runs
  add column if not exists available_at timestamptz not null default now();
alter table public.agent_tasks
  add column if not exists available_at timestamptz not null default now();

create index if not exists production_runs_due_queue_idx
  on public.production_runs(available_at,created_at)
  where status='queued';

create or replace function private.graphytion_claim_creative_run(
  p_worker_id text,
  p_run_id uuid default null,
  p_lease_seconds integer default 120
)
returns table(
  run_id uuid,
  project_id uuid,
  workspace_id uuid,
  requested_by uuid,
  input_snapshot jsonb,
  current_stage text,
  attempt_count integer,
  worker_id text
)
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_run public.production_runs%rowtype;
begin
  if p_worker_id is null or char_length(p_worker_id) not between 1 and 128 then
    raise exception 'invalid worker identity';
  end if;
  if p_lease_seconds < 30 or p_lease_seconds > 900 then
    raise exception 'invalid lease duration';
  end if;

  with candidate as (
    select r.id
    from public.production_runs r
    where (p_run_id is null or r.id = p_run_id)
      and r.cancel_requested_at is null
      and r.attempt_count < r.max_attempts
      and (
        (r.status = 'queued' and r.available_at <= now())
        or (
          r.status in ('planning','scripting','storyboarding')
          and (r.lease_expires_at is null or r.lease_expires_at < now())
        )
      )
    order by r.available_at,r.created_at
    for update skip locked
    limit 1
  )
  update public.production_runs r
  set status = case r.input_snapshot->>'stage'
        when 'brief' then 'planning'
        when 'script' then 'scripting'
        when 'storyboard' then 'storyboarding'
        when 'scene' then 'storyboarding'
        else r.status
      end,
      current_stage = r.input_snapshot->>'stage',
      worker_id = p_worker_id,
      lease_expires_at = now() + make_interval(secs => p_lease_seconds),
      attempt_count = r.attempt_count + 1,
      started_at = coalesce(r.started_at, now())
  from candidate c
  where r.id = c.id
  returning r.* into v_run;

  if v_run.id is null then
    return;
  end if;

  return query select
    v_run.id, v_run.project_id, v_run.workspace_id, v_run.requested_by,
    v_run.input_snapshot, v_run.current_stage, v_run.attempt_count, v_run.worker_id;
end;
$$;

revoke all on function private.graphytion_claim_creative_run(text,uuid,integer)
  from public, anon, authenticated, service_role;
grant execute on function private.graphytion_claim_creative_run(text,uuid,integer)
  to graphytion_api;

commit;
