-- Background dispatcher reconciliation and failure recording must be independent
-- of request-scoped RLS claims; expose only narrow, worker-authorized functions.
begin;

create or replace function private.graphytion_reconcile_active_production_runs(
  p_limit integer default 50
)
returns integer
language plpgsql
security definer
set search_path = pg_catalog, public, private, pg_temp
as $$
declare
  v_run record;
  v_step record;
  v_sequence bigint;
  v_count integer := 0;
begin
  if p_limit < 1 or p_limit > 200 then
    raise exception 'invalid production run reconciliation limit';
  end if;

  for v_run in
    select id,status
      from public.production_runs
     where status in ('queued','planning','ready_for_review','cancel_requested')
        or cancel_requested_at is not null
     order by updated_at
     limit p_limit
  loop
    if v_run.status='cancel_requested' then
      perform 1 from public.production_runs where id=v_run.id for update;
      for v_step in
        update public.production_run_steps
           set status='cancelled',worker_id=null,lease_expires_at=null,
               heartbeat_at=null,completed_at=now(),error_code='RUN_CANCELLED',
               error_message_safe='Production Run cancellation was requested',
               external_operation_state='not_started',updated_at=now()
         where production_run_id=v_run.id and child_job_id is null
           and status in ('pending','ready','waiting_approval','running')
        returning id,step_key
      loop
        select coalesce(max(sequence_number),0)+1 into v_sequence
          from public.workflow_events where production_run_id=v_run.id;
        insert into public.workflow_events(
          production_run_id,event_type,event_payload,sequence_number
        ) values(
          v_run.id,'step.cancelled',
          jsonb_build_object('step_id',v_step.id,'step_key',v_step.step_key,
            'reason','production_run_cancelled'),
          v_sequence
        ) on conflict(production_run_id,sequence_number) do nothing;
      end loop;
    end if;

    perform private.graphytion_sync_production_run(v_run.id);
    v_count := v_count + 1;
  end loop;
  return v_count;
end;
$$;

create or replace function private.graphytion_record_step_failure(
  p_step_id uuid,
  p_worker_id text,
  p_error_code text,
  p_error_message text,
  p_error_class text,
  p_retryable boolean default false,
  p_cancelled boolean default false
)
returns boolean
language plpgsql
security definer
set search_path = pg_catalog, public, private, pg_temp
as $$
declare
  v_step record;
  v_retry boolean;
  v_delay integer;
  v_sequence bigint;
  v_event_type text;
begin
  select production_run_id,step_key,attempt_count,max_attempts,status,worker_id
    into v_step
    from public.production_run_steps
   where id=p_step_id
   for update;
  if not found or v_step.status<>'running' or v_step.worker_id<>p_worker_id then
    return false;
  end if;

  v_retry := p_retryable and not p_cancelled and v_step.attempt_count < v_step.max_attempts;
  v_delay := least(300,(2 ^ least(v_step.attempt_count,8))::integer);

  update public.production_run_steps
     set status=case when p_cancelled then 'cancelled' when v_retry then 'ready' else 'failed' end,
         worker_id=null,lease_expires_at=null,heartbeat_at=null,
         retry_count=retry_count+case when v_retry then 1 else 0 end,
         next_retry_at=case when v_retry then now()+make_interval(secs=>v_delay) else null end,
         available_at=case when v_retry then now()+make_interval(secs=>v_delay) else available_at end,
         error_code=left(coalesce(p_error_code,'STEP_EXECUTION_FAILED'),120),
         error_message_safe=left(coalesce(p_error_message,'Step execution failed'),500),
         last_error_class=case when p_cancelled then 'cancelled'
           when v_retry then 'transient' else coalesce(p_error_class,'permanent') end,
         last_error_at=now(),
         completed_at=case when v_retry then null else now() end,
         external_operation_state=case when p_cancelled then 'not_started'
           when external_operation_state in ('submitted','reconciling','unknown')
           then 'unknown' else 'failed' end,
         updated_at=now()
   where id=p_step_id and worker_id=p_worker_id;

  perform 1 from public.production_runs where id=v_step.production_run_id for update;
  select coalesce(max(sequence_number),0)+1 into v_sequence
    from public.workflow_events where production_run_id=v_step.production_run_id;
  v_event_type := case when p_cancelled then 'step.cancelled'
    when v_retry then 'step.retry' else 'step.failed' end;
  insert into public.workflow_events(
    production_run_id,event_type,event_payload,sequence_number
  ) values(
    v_step.production_run_id,v_event_type,
    jsonb_build_object('step_id',p_step_id,'step_key',v_step.step_key,
      'worker_id',p_worker_id,'retryable',v_retry,
      'retry_delay_seconds',case when v_retry then v_delay else null end,
      'error_code',p_error_code,'error_class',
      case when p_cancelled then 'cancelled' when v_retry then 'transient'
           else coalesce(p_error_class,'permanent') end),
    v_sequence
  ) on conflict(production_run_id,sequence_number) do nothing;

  perform private.graphytion_sync_production_run(v_step.production_run_id);
  return true;
end;
$$;

revoke all on function private.graphytion_reconcile_active_production_runs(integer)
  from public,anon,authenticated,service_role;
revoke all on function private.graphytion_record_step_failure(uuid,text,text,text,text,boolean,boolean)
  from public,anon,authenticated,service_role;
grant execute on function private.graphytion_reconcile_active_production_runs(integer)
  to graphytion_api,graphytion_runtime;
grant execute on function private.graphytion_record_step_failure(uuid,text,text,text,text,boolean,boolean)
  to graphytion_api,graphytion_runtime;

commit;
