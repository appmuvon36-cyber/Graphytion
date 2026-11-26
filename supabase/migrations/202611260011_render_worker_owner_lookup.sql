-- Narrow internal render ownership lookup used only after worker-token authentication.
begin;

create or replace function private.graphytion_render_job_owner(p_job_id uuid, p_worker_id text)
returns uuid
language sql
stable
security definer
set search_path = ''
as $$
  select requested_by
  from public.render_jobs
  where id=p_job_id and worker_id=p_worker_id and status='rendering'
  limit 1;
$$;

revoke all on function private.graphytion_render_job_owner(uuid,text)
  from public, anon, authenticated, service_role;
grant execute on function private.graphytion_render_job_owner(uuid,text)
  to graphytion_api;

commit;
