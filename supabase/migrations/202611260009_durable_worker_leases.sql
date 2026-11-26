-- Durable worker leases and narrowly scoped database claiming function.
-- PostgreSQL remains authoritative; Redis only wakes workers.
begin;

alter table public.production_runs
  add column if not exists worker_id text,
  add column if not exists lease_expires_at timestamptz,
  add column if not exists attempt_count integer not null default 0,
  add column if not exists max_attempts integer not null default 3,
  add column if not exists cancel_requested_at timestamptz,
  add column if not exists cancelled_at timestamptz;

alter table public.production_runs
  drop constraint if exists production_runs_attempt_count_check;
alter table public.production_runs
  add constraint production_runs_attempt_count_check
  check (attempt_count >= 0 and max_attempts between 1 and 10);

create index if not exists production_runs_worker_recovery_idx
  on public.production_runs(status,lease_expires_at,created_at)
  where status in ('queued','planning','scripting','storyboarding');

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
  attempt_count integer
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
        r.status = 'queued'
        or (
          r.status in ('planning','scripting','storyboarding')
          and (r.lease_expires_at is null or r.lease_expires_at < now())
        )
      )
    order by r.created_at
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
    v_run.input_snapshot, v_run.current_stage, v_run.attempt_count;
end;
$$;

revoke all on function private.graphytion_claim_creative_run(text,uuid,integer)
  from public, anon, authenticated, service_role;
grant execute on function private.graphytion_claim_creative_run(text,uuid,integer)
  to graphytion_api;

commit;
