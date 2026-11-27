-- Persistent DAG dispatcher: additive, restart-safe orchestration leases and versioned contracts.
begin;

alter table public.production_run_steps
  add column if not exists payload_schema_version integer not null default 1,
  add column if not exists payload_contract jsonb not null default '{}'::jsonb,
  add column if not exists input_fingerprint text,
  add column if not exists worker_id text,
  add column if not exists claimed_at timestamptz,
  add column if not exists heartbeat_at timestamptz,
  add column if not exists lease_expires_at timestamptz,
  add column if not exists retry_count integer not null default 0,
  add column if not exists next_retry_at timestamptz,
  add column if not exists last_error_class text,
  add column if not exists last_error_at timestamptz,
  add column if not exists external_operation_state text;

alter table public.production_run_steps
  add constraint production_run_steps_payload_version_check
    check (payload_schema_version between 1 and 100),
  add constraint production_run_steps_retry_count_check
    check (retry_count >= 0),
  add constraint production_run_steps_external_operation_state_check
    check (external_operation_state is null or external_operation_state in
      ('not_started','submitted','reconciling','completed','failed','unknown'));

create index if not exists production_run_steps_dispatch_ready_idx
  on public.production_run_steps(available_at,created_at)
  where status='ready' and child_job_id is null;
create index if not exists production_run_steps_dispatch_expired_idx
  on public.production_run_steps(lease_expires_at)
  where status='running' and child_job_id is null;
create index if not exists production_run_steps_worker_lease_idx
  on public.production_run_steps(worker_id,lease_expires_at)
  where worker_id is not null;

create or replace function private.graphytion_claim_production_step(
  p_worker_id text,
  p_lease_seconds integer default 120
)
returns setof public.production_run_steps
language plpgsql
security definer
set search_path = pg_catalog, public, private, pg_temp
as $$
declare
  v_step public.production_run_steps%rowtype;
  v_run_id uuid;
  v_sequence bigint;
begin
  if p_worker_id is null or length(btrim(p_worker_id)) < 3 or length(p_worker_id) > 128 then
    raise exception 'invalid orchestrator worker identity';
  end if;
  if p_lease_seconds < 30 or p_lease_seconds > 900 then
    raise exception 'invalid orchestrator lease duration';
  end if;

  -- Only reclaim orchestration-owned steps. Once a child row exists, its
  -- dedicated media/render worker owns recovery and provider reconciliation.
  for v_step in
    update public.production_run_steps s
       set status=case when s.attempt_count >= s.max_attempts then 'failed' else 'ready' end,
           worker_id=null, lease_expires_at=null, heartbeat_at=null,
           retry_count=s.retry_count+1,
           next_retry_at=case when s.attempt_count >= s.max_attempts then null
             else now()+make_interval(secs=>least(300,(2 ^ least(s.retry_count,8))::integer)) end,
           available_at=case when s.attempt_count >= s.max_attempts then s.available_at
             else now()+make_interval(secs=>least(300,(2 ^ least(s.retry_count,8))::integer)) end,
           error_code=case when s.attempt_count >= s.max_attempts then 'STEP_LEASE_EXHAUSTED' else 'STEP_LEASE_EXPIRED' end,
           error_message_safe='Orchestrator lease expired before a child job was persisted',
           last_error_class='lease_expired',last_error_at=now(),
           completed_at=case when s.attempt_count >= s.max_attempts then now() else null end,
           updated_at=now()
     where s.status='running' and s.child_job_id is null
       and s.lease_expires_at is not null and s.lease_expires_at < now()
    returning s.*
  loop
    v_run_id := v_step.production_run_id;
    perform 1 from public.production_runs r where r.id=v_run_id for update;
    select coalesce(max(e.sequence_number),0)+1 into v_sequence
      from public.workflow_events e where e.production_run_id=v_run_id;
    insert into public.workflow_events(production_run_id,event_type,event_payload,sequence_number)
    values(v_run_id,
      case when v_step.status='failed' then 'step.timeout' else 'step.recovered' end,
      jsonb_build_object('step_id',v_step.id,'step_key',v_step.step_key,
        'worker_id',p_worker_id,'attempt_count',v_step.attempt_count,
        'retry_count',v_step.retry_count,'error_code',v_step.error_code),
      v_sequence)
    on conflict(production_run_id,sequence_number) do nothing;
  end loop;

  select s.* into v_step
    from public.production_run_steps s
    join public.production_runs r on r.id=s.production_run_id
   where s.status='ready'
     and s.child_job_id is null
     and s.available_at <= now()
     and coalesce(r.status,'') not in ('cancel_requested','cancelled','failed','completed')
     and not exists (
       select 1 from public.production_run_step_dependencies d
       join public.production_run_steps parent on parent.id=d.depends_on_step_id
       where d.step_id=s.id and parent.status<>'completed'
     )
   order by s.available_at,s.created_at,s.id
   for update of s skip locked
   limit 1;

  if not found then return; end if;

  update public.production_run_steps
     set status='running',worker_id=p_worker_id,claimed_at=now(),
         heartbeat_at=now(),
         lease_expires_at=now()+make_interval(secs=>p_lease_seconds),
         attempt_count=attempt_count+1,
         started_at=coalesce(started_at,now()),
         error_code=null,error_message_safe=null,
         last_error_class=null,last_error_at=null,
         next_retry_at=null,updated_at=now()
   where id=v_step.id
   returning * into v_step;

  perform 1 from public.production_runs r where r.id=v_step.production_run_id for update;
  select coalesce(max(e.sequence_number),0)+1 into v_sequence
    from public.workflow_events e where e.production_run_id=v_step.production_run_id;
  insert into public.workflow_events(production_run_id,event_type,event_payload,sequence_number)
  values(v_step.production_run_id,'step.claimed',
    jsonb_build_object('step_id',v_step.id,'step_key',v_step.step_key,
      'step_type',v_step.step_type,'worker_id',p_worker_id,
      'attempt_count',v_step.attempt_count,'lease_expires_at',v_step.lease_expires_at),
    v_sequence)
  on conflict(production_run_id,sequence_number) do nothing;

  return next v_step;
end;
$$;

create or replace function private.graphytion_heartbeat_production_step(
  p_step_id uuid,
  p_worker_id text,
  p_lease_seconds integer default 120
)
returns boolean
language sql
security definer
set search_path = pg_catalog, public, private, pg_temp
as $$
  update public.production_run_steps
     set heartbeat_at=now(),
         lease_expires_at=now()+make_interval(secs=>p_lease_seconds),
         updated_at=now()
   where id=p_step_id and status='running'
     and worker_id=p_worker_id and child_job_id is null
     and lease_expires_at > now()
  returning true;
$$;

revoke all on function private.graphytion_claim_production_step(text,integer) from public,anon,authenticated,service_role;
revoke all on function private.graphytion_heartbeat_production_step(uuid,text,integer) from public,anon,authenticated,service_role;
grant execute on function private.graphytion_claim_production_step(text,integer) to graphytion_api,graphytion_runtime;
grant execute on function private.graphytion_heartbeat_production_step(uuid,text,integer) to graphytion_api,graphytion_runtime;

commit;
