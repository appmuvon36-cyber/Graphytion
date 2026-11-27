-- Persist every production step state transition in the existing run event stream.
begin;
create or replace function private.graphytion_record_production_step_transition()
returns trigger
language plpgsql
security invoker
set search_path = public, private, pg_temp
as $$
begin
  if old.status is distinct from new.status then
    perform pg_advisory_xact_lock(hashtextextended(new.production_run_id::text,0));
    insert into public.workflow_events(production_run_id,event_type,event_payload,sequence_number)
    values (
      new.production_run_id,
      'step.'||new.status,
      jsonb_build_object(
        'step_id',new.id,'step_key',new.step_key,
        'from_status',old.status,'to_status',new.status,
        'child_job_type',new.child_job_type,'child_job_id',new.child_job_id,
        'error_code',new.error_code
      ),
      (select coalesce(max(sequence_number),0)+1
       from public.workflow_events where production_run_id=new.production_run_id)
    );
  end if;
  return new;
end;
$$;
drop trigger if exists production_run_step_transition_history on public.production_run_steps;
create trigger production_run_step_transition_history
after update of status on public.production_run_steps
for each row execute function private.graphytion_record_production_step_transition();
revoke all on function private.graphytion_record_production_step_transition() from public,anon,authenticated;
grant execute on function private.graphytion_record_production_step_transition() to graphytion_api,graphytion_runtime;
commit;
