-- Worker presence registry and capacity accounting for cancellation-in-flight jobs.
begin;

create table if not exists public.worker_heartbeats (
  worker_id text primary key check (char_length(worker_id) between 1 and 128),
  worker_type text not null check (worker_type in ('media','render')),
  hostname text not null check (char_length(hostname) between 1 and 255),
  version text,
  status text not null default 'online' check (status in ('online','draining')),
  metadata jsonb not null default '{}'::jsonb,
  started_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.worker_heartbeats enable row level security;
drop policy if exists worker_heartbeats_admin_read on public.worker_heartbeats;
create policy worker_heartbeats_admin_read
on public.worker_heartbeats
for select to graphytion_api
using (private.graphytion_is_platform_admin());
revoke all on public.worker_heartbeats from public, anon, authenticated, service_role;
grant select on public.worker_heartbeats to graphytion_api;

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
  on conflict (worker_id) do update
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
          where r.status in ('rendering','cancel_requested')
            and r.lease_expires_at > now())
  from public.platform_render_settings s
  where s.singleton_id=1;
$$;

revoke all on function private.graphytion_render_runtime_capacity()
  from public, anon, authenticated, service_role;
grant execute on function private.graphytion_render_runtime_capacity()
  to graphytion_api;

commit;
