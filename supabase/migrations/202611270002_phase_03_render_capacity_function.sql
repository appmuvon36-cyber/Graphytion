-- Expose a minimal security-definer view of global render capacity to the
-- authenticated internal worker claim path without granting cross-tenant job reads.
begin;

create or replace function private.graphytion_render_runtime_capacity()
returns table (
  max_concurrent_jobs smallint,
  lease_seconds integer,
  max_attempts smallint,
  max_output_bytes bigint,
  active_jobs bigint
)
language sql
stable
security definer
set search_path = ''
as $$
  select s.max_concurrent_jobs,
         s.lease_seconds,
         s.max_attempts,
         s.max_output_bytes,
         (select count(*)::bigint
          from public.render_jobs r
          where r.status='rendering' and r.lease_expires_at > now())
  from public.platform_render_settings s
  where s.singleton_id=1;
$$;

revoke all on function private.graphytion_render_runtime_capacity()
  from public, anon, authenticated, service_role;
grant execute on function private.graphytion_render_runtime_capacity()
  to graphytion_api;

commit;
