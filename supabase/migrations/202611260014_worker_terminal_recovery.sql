-- Finalize abandoned jobs after the final lease expires; no work is left permanently stuck.
begin;

create or replace function private.graphytion_finalize_creative_runs()
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_failed uuid[];
  v_cancelled uuid[];
begin
  select array_agg(id) into v_failed
  from public.production_runs
  where status in ('planning','scripting','storyboarding')
    and lease_expires_at < now()
    and attempt_count >= max_attempts
  for update;

  if coalesce(cardinality(v_failed),0) > 0 then
    update public.production_runs set status='failed',
      error_code='MAX_ATTEMPTS_EXCEEDED',
      error_message_safe='Creative worker stopped before completing the run',
      completed_at=now(),worker_id=null,lease_expires_at=null
    where id=any(v_failed);
    update public.agent_tasks set status='failed',
      error_code='MAX_ATTEMPTS_EXCEEDED',completed_at=now(),lease_expires_at=null
    where production_run_id=any(v_failed) and status in ('running','retry_wait','queued');
  end if;

  select array_agg(id) into v_cancelled
  from public.production_runs
  where status='cancel_requested' and lease_expires_at < now()
  for update;

  if coalesce(cardinality(v_cancelled),0) > 0 then
    update public.production_runs set status='cancelled',cancelled_at=now(),
      completed_at=now(),worker_id=null,lease_expires_at=null
    where id=any(v_cancelled);
    update public.agent_tasks set status='cancelled',completed_at=now(),lease_expires_at=null
    where production_run_id=any(v_cancelled) and status in ('running','retry_wait','queued');
  end if;

  return coalesce(cardinality(v_failed),0)+coalesce(cardinality(v_cancelled),0);
end;
$$;

create or replace function private.graphytion_finalize_render_jobs()
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_failed uuid[];
  v_cancelled uuid[];
begin
  select array_agg(id) into v_failed
  from public.render_jobs
  where status='rendering' and lease_expires_at < now()
    and attempt_count >= max_attempts
  for update;
  if coalesce(cardinality(v_failed),0) > 0 then
    update public.render_jobs set status='failed',error_code='MAX_ATTEMPTS_EXCEEDED',
      error_message_safe='Render worker stopped before completing the job',
      completed_at=now(),worker_id=null,lease_expires_at=null
    where id=any(v_failed);
  end if;

  select array_agg(id) into v_cancelled
  from public.render_jobs
  where status='cancel_requested' and lease_expires_at < now()
  for update;
  if coalesce(cardinality(v_cancelled),0) > 0 then
    update public.render_jobs set status='cancelled',completed_at=now(),
      worker_id=null,lease_expires_at=null
    where id=any(v_cancelled);
  end if;

  return coalesce(cardinality(v_failed),0)+coalesce(cardinality(v_cancelled),0);
end;
$$;

revoke all on function private.graphytion_finalize_creative_runs() from public, anon, authenticated, service_role;
revoke all on function private.graphytion_finalize_render_jobs() from public, anon, authenticated, service_role;
grant execute on function private.graphytion_finalize_creative_runs() to graphytion_api;
grant execute on function private.graphytion_finalize_render_jobs() to graphytion_api;

commit;
