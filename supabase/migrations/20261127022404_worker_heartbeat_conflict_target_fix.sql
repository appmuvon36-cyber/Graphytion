-- Fix ambiguous ON CONFLICT target in worker heartbeat upsert.
-- The function's RETURNS TABLE exposes worker_id as an output variable;
-- use the primary-key constraint name to avoid PL/pgSQL name ambiguity.
create or replace function private.graphytion_upsert_worker_heartbeat(
  p_worker_id text,
  p_worker_type text,
  p_hostname text,
  p_version text,
  p_metadata jsonb default '{}'::jsonb
)
returns table(worker_id text, worker_type text, status text, last_seen_at timestamptz)
language plpgsql
security definer
set search_path = ''
as $$
begin
  if p_worker_type not in ('media','render')
     or p_worker_id is null or char_length(p_worker_id) not between 1 and 128
     or p_hostname is null or char_length(p_hostname) not between 1 and 255 then
    raise exception 'invalid worker heartbeat identity';
  end if;

  return query
  insert into public.worker_heartbeats as current_worker
    (worker_id,worker_type,hostname,version,status,metadata,started_at,last_seen_at,updated_at)
  values
    (p_worker_id,p_worker_type,p_hostname,p_version,'online',coalesce(p_metadata,'{}'::jsonb),now(),now(),now())
  on conflict on constraint worker_heartbeats_pkey do update
    set worker_type=excluded.worker_type,
        hostname=excluded.hostname,
        version=excluded.version,
        status='online',
        metadata=excluded.metadata,
        last_seen_at=now(),
        updated_at=now()
  returning current_worker.worker_id,current_worker.worker_type,current_worker.status,current_worker.last_seen_at;
end;
$$;

revoke all on function private.graphytion_upsert_worker_heartbeat(text,text,text,text,jsonb)
  from public, anon, authenticated, service_role;
grant execute on function private.graphytion_upsert_worker_heartbeat(text,text,text,text,jsonb)
  to graphytion_api;
