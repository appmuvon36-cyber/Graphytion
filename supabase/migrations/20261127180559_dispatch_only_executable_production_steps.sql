-- Keep derived artifact-reconciliation nodes in the existing SQL state machine.
-- The background dispatcher only claims steps that require an executable handler.
begin;
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
     and s.step_type in ('creative','media_generation','voiceover','subtitle','timeline','render')
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
revoke all on function private.graphytion_claim_production_step(text,integer) from public,anon,authenticated,service_role;
grant execute on function private.graphytion_claim_production_step(text,integer) to graphytion_api,graphytion_runtime;
commit;
