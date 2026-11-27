begin;

alter table public.media_generation_jobs
  alter column quota_reconciliation_status set default 'not_required';

create index if not exists media_generation_legacy_quota_recovery_idx
  on public.media_generation_jobs(completed_at)
  where quota_reservation_id is not null
    and quota_reconciliation_status='pending';

create or replace function private.graphytion_pending_media_reconciliation_jobs(p_limit integer default 50)
returns setof public.media_generation_jobs
language sql security definer set search_path='' as $$
  select j.* from public.media_generation_jobs j
  where j.status in ('completed','failed','cancelled')
    and j.quota_reservation_id is not null
    and j.quota_reconciliation_status='pending'
  order by j.completed_at asc
  for update skip locked
  limit least(greatest(coalesce(p_limit,50),1),100)
$$;

revoke all on function private.graphytion_pending_media_reconciliation_jobs(integer)
  from public,anon,authenticated,service_role;
grant execute on function private.graphytion_pending_media_reconciliation_jobs(integer)
  to graphytion_api;

commit;
