-- Give the persistent dispatcher a narrow, ownership-checked way to load
-- the run context before setting the tenant RLS subject.
begin;

create or replace function private.graphytion_get_dispatch_run_context(
  p_step_id uuid,
  p_worker_id text
)
returns table (
  id uuid,
  workspace_id uuid,
  project_id uuid,
  requested_by uuid,
  status text,
  input_snapshot jsonb,
  config_snapshot jsonb,
  cancel_requested_at timestamptz
)
language sql
security definer
set search_path = pg_catalog, public, private
as $$
  select r.id, r.workspace_id, r.project_id, r.requested_by, r.status,
         r.input_snapshot, r.config_snapshot, r.cancel_requested_at
  from public.production_run_steps s
  join public.production_runs r on r.id = s.production_run_id
  where s.id = p_step_id
    and s.worker_id = p_worker_id
    and s.status = 'running'
    and r.workspace_id = s.workspace_id
    and r.project_id = s.project_id
$$;

revoke all on function private.graphytion_get_dispatch_run_context(uuid,text)
  from public, anon, authenticated;
grant execute on function private.graphytion_get_dispatch_run_context(uuid,text)
  to graphytion_api, graphytion_runtime;

commit;
