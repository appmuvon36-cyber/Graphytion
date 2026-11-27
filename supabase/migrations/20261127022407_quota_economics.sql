-- Atomic workspace quota reservations and auditable usage ledger.
begin;

create table if not exists public.workspace_quota_accounts (
  workspace_id uuid primary key references public.workspaces(id) on delete cascade,
  quota_limit_microusd bigint not null check (quota_limit_microusd > 0),
  consumed_microusd bigint not null default 0 check (consumed_microusd >= 0),
  reserved_microusd bigint not null default 0 check (reserved_microusd >= 0),
  period_start timestamptz not null,
  period_end timestamptz not null,
  status text not null default 'active' check (status in ('active','paused')),
  updated_by uuid references public.profiles(id) on delete set null,
  updated_at timestamptz not null default now(),
  check (period_end > period_start)
);

create table if not exists public.quota_reservations (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  project_id uuid not null references public.video_projects(id) on delete cascade,
  resource_type text not null check (resource_type in ('creative_run','voiceover','render_job','image_generation','video_generation')),
  resource_id uuid not null,
  idempotency_key text not null check (char_length(idempotency_key) between 16 and 180),
  reserved_microusd bigint not null check (reserved_microusd > 0),
  consumed_microusd bigint not null default 0 check (consumed_microusd >= 0),
  status text not null default 'reserved' check (status in ('reserved','consumed','released','reversed','expired')),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(workspace_id,idempotency_key),
);
create index if not exists quota_reservations_resource_idx
  on public.quota_reservations(resource_type,resource_id,created_at desc);
create index if not exists quota_reservations_workspace_status_idx
  on public.quota_reservations(workspace_id,status,created_at desc);

create table if not exists public.quota_ledger_entries (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  reservation_id uuid references public.quota_reservations(id) on delete restrict,
  entry_type text not null check (entry_type in ('reserve','consume','release','reversal','adjustment')),
  amount_microusd bigint not null check (amount_microusd <> 0),
  idempotency_key text not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique(workspace_id,idempotency_key)
);
create index if not exists quota_ledger_workspace_created_idx
  on public.quota_ledger_entries(workspace_id,created_at desc);

create table if not exists public.quota_operation_prices (
  id uuid primary key default gen_random_uuid(),
  operation_key text not null check (operation_key in ('voiceover_per_1000_chars','render_per_second','image_generation','video_generation')),
  microusd_per_unit bigint not null check (microusd_per_unit >= 0),
  unit_name text not null,
  effective_at timestamptz not null default now(),
  is_active boolean not null default true,
  notes text,
  created_by uuid references public.profiles(id) on delete set null,
  created_at timestamptz not null default now(),
  unique(operation_key,effective_at)
);

create or replace function private.graphytion_reserve_quota(
  p_workspace_id uuid,p_project_id uuid,p_resource_type text,p_resource_id uuid,
  p_idempotency_key text,p_amount_microusd bigint,p_metadata jsonb default '{}'::jsonb
) returns uuid language plpgsql security definer set search_path='' as $$
declare account_row public.workspace_quota_accounts%rowtype;
declare existing_row public.quota_reservations%rowtype;
declare reservation_id uuid;
begin
  if p_amount_microusd <= 0 then raise exception using errcode='P0001',message='QUOTA_AMOUNT_INVALID'; end if;
  if not private.graphytion_is_workspace_member(p_workspace_id) then
    raise exception using errcode='42501',message='WORKSPACE_ACCESS_DENIED';
  end if;
  select * into existing_row from public.quota_reservations
    where workspace_id=p_workspace_id and idempotency_key=p_idempotency_key for update;
  if found then
    if existing_row.project_id<>p_project_id or existing_row.resource_type<>p_resource_type
      or existing_row.resource_id<>p_resource_id or existing_row.reserved_microusd<>p_amount_microusd then
      raise exception using errcode='23505',message='QUOTA_IDEMPOTENCY_CONFLICT';
    end if;
    return existing_row.id;
  end if;
  select * into account_row from public.workspace_quota_accounts
    where workspace_id=p_workspace_id for update;
  if not found or account_row.status<>'active' or now()<account_row.period_start or now()>=account_row.period_end then
    raise exception using errcode='P0001',message='QUOTA_ACCOUNT_UNAVAILABLE';
  end if;
  if account_row.quota_limit_microusd-account_row.consumed_microusd-account_row.reserved_microusd < p_amount_microusd then
    raise exception using errcode='P0001',message='QUOTA_EXCEEDED';
  end if;
  insert into public.quota_reservations(workspace_id,project_id,resource_type,resource_id,idempotency_key,reserved_microusd,metadata)
    values(p_workspace_id,p_project_id,p_resource_type,p_resource_id,p_idempotency_key,p_amount_microusd,coalesce(p_metadata,'{}'::jsonb))
    returning id into reservation_id;
  update public.workspace_quota_accounts set reserved_microusd=reserved_microusd+p_amount_microusd,updated_at=now()
    where workspace_id=p_workspace_id;
  insert into public.quota_ledger_entries(workspace_id,reservation_id,entry_type,amount_microusd,idempotency_key,metadata)
    values(p_workspace_id,reservation_id,'reserve',p_amount_microusd,'reserve:'||p_idempotency_key,coalesce(p_metadata,'{}'::jsonb));
  return reservation_id;
end $$;

create or replace function private.graphytion_reconcile_quota(
  p_reservation_id uuid,p_actual_cost_microusd bigint,p_metadata jsonb default '{}'::jsonb
) returns void language plpgsql security definer set search_path='' as $$
declare reservation_row public.quota_reservations%rowtype;
declare delta bigint;
begin
  if p_actual_cost_microusd < 0 then raise exception using errcode='P0001',message='QUOTA_COST_INVALID'; end if;
  select * into reservation_row from public.quota_reservations where id=p_reservation_id for update;
  if not found then raise exception using errcode='P0002',message='QUOTA_RESERVATION_NOT_FOUND'; end if;
  if not private.graphytion_is_workspace_member(reservation_row.workspace_id) then
    raise exception using errcode='42501',message='WORKSPACE_ACCESS_DENIED';
  end if;
  if reservation_row.status='consumed' then
    if reservation_row.consumed_microusd=p_actual_cost_microusd then return; end if;
    raise exception using errcode='23505',message='QUOTA_RECONCILIATION_CONFLICT';
  end if;
  if reservation_row.status<>'reserved' then
    raise exception using errcode='P0001',message='QUOTA_RESERVATION_NOT_ACTIVE';
  end if;
  perform 1 from public.workspace_quota_accounts where workspace_id=reservation_row.workspace_id for update;
  update public.workspace_quota_accounts
    set reserved_microusd=greatest(0,reserved_microusd-reservation_row.reserved_microusd),
        consumed_microusd=consumed_microusd+p_actual_cost_microusd,updated_at=now()
    where workspace_id=reservation_row.workspace_id;
  update public.quota_reservations set status='consumed',consumed_microusd=p_actual_cost_microusd,
    metadata=metadata||coalesce(p_metadata,'{}'::jsonb),updated_at=now() where id=p_reservation_id;
  if p_actual_cost_microusd>0 then
    insert into public.quota_ledger_entries(workspace_id,reservation_id,entry_type,amount_microusd,idempotency_key,metadata)
      values(reservation_row.workspace_id,p_reservation_id,'consume',p_actual_cost_microusd,'consume:'||p_reservation_id::text,coalesce(p_metadata,'{}'::jsonb));
  end if;
  delta=reservation_row.reserved_microusd-p_actual_cost_microusd;
  if delta>0 then
    insert into public.quota_ledger_entries(workspace_id,reservation_id,entry_type,amount_microusd,idempotency_key,metadata)
      values(reservation_row.workspace_id,p_reservation_id,'release',-delta,'reconcile-release:'||p_reservation_id::text,'{}'::jsonb);
  elsif delta<0 then
    insert into public.quota_ledger_entries(workspace_id,reservation_id,entry_type,amount_microusd,idempotency_key,metadata)
      values(reservation_row.workspace_id,p_reservation_id,'adjustment',-delta,'reconcile-overage:'||p_reservation_id::text,
        jsonb_build_object('reason','actual_cost_exceeded_reservation'));
  end if;
end $$;

create or replace function private.graphytion_release_quota(
  p_reservation_id uuid,p_reason text default 'released'
) returns void language plpgsql security definer set search_path='' as $$
declare reservation_row public.quota_reservations%rowtype;
begin
  select * into reservation_row from public.quota_reservations where id=p_reservation_id for update;
  if not found then return; end if;
  if not private.graphytion_is_workspace_member(reservation_row.workspace_id) then
    raise exception using errcode='42501',message='WORKSPACE_ACCESS_DENIED';
  end if;
  if reservation_row.status='released' then return; end if;
  if reservation_row.status<>'reserved' then return; end if;
  update public.workspace_quota_accounts set
    reserved_microusd=greatest(0,reserved_microusd-reservation_row.reserved_microusd),updated_at=now()
    where workspace_id=reservation_row.workspace_id;
  update public.quota_reservations set status='released',updated_at=now(),
    metadata=metadata||jsonb_build_object('release_reason',left(coalesce(p_reason,'released'),120))
    where id=p_reservation_id;
  insert into public.quota_ledger_entries(workspace_id,reservation_id,entry_type,amount_microusd,idempotency_key,metadata)
    values(reservation_row.workspace_id,p_reservation_id,'release',-reservation_row.reserved_microusd,
      'release:'||p_reservation_id::text,jsonb_build_object('reason',left(coalesce(p_reason,'released'),120)));
end $$;

create or replace function private.graphytion_reverse_quota(
  p_reservation_id uuid,p_amount_microusd bigint,p_idempotency_key text,p_reason text
) returns void language plpgsql security definer set search_path='' as $$
declare reservation_row public.quota_reservations%rowtype;
begin
  if p_amount_microusd<=0 then raise exception using errcode='P0001',message='QUOTA_REVERSAL_AMOUNT_INVALID'; end if;
  select * into reservation_row from public.quota_reservations where id=p_reservation_id for update;
  if not found then raise exception using errcode='P0002',message='QUOTA_RESERVATION_NOT_FOUND'; end if;
  if not private.graphytion_is_workspace_member(reservation_row.workspace_id)
     and not private.graphytion_is_platform_admin() then
    raise exception using errcode='42501',message='WORKSPACE_ACCESS_DENIED';
  end if;
  if exists(select 1 from public.quota_ledger_entries where workspace_id=reservation_row.workspace_id
      and idempotency_key=p_idempotency_key and reservation_id=p_reservation_id) then return; end if;
  if exists(select 1 from public.quota_ledger_entries where workspace_id=reservation_row.workspace_id
      and idempotency_key=p_idempotency_key) then
    raise exception using errcode='23505',message='QUOTA_REVERSAL_IDEMPOTENCY_CONFLICT';
  end if;
  if reservation_row.status not in ('consumed','reversed') or reservation_row.consumed_microusd<p_amount_microusd then
    raise exception using errcode='P0001',message='QUOTA_REVERSAL_EXCEEDS_CONSUMPTION';
  end if;
  update public.workspace_quota_accounts set consumed_microusd=greatest(0,consumed_microusd-p_amount_microusd),updated_at=now()
    where workspace_id=reservation_row.workspace_id;
  update public.quota_reservations set consumed_microusd=consumed_microusd-p_amount_microusd,
    status=case when consumed_microusd-p_amount_microusd=0 then 'reversed' else 'consumed' end,updated_at=now()
    where id=p_reservation_id;
  insert into public.quota_ledger_entries(workspace_id,reservation_id,entry_type,amount_microusd,idempotency_key,metadata)
    values(reservation_row.workspace_id,p_reservation_id,'reversal',-p_amount_microusd,p_idempotency_key,
      jsonb_build_object('reason',left(coalesce(p_reason,'reversal'),240)));
end $$;

alter table public.workspace_quota_accounts enable row level security;
alter table public.quota_reservations enable row level security;
alter table public.quota_ledger_entries enable row level security;
alter table public.quota_operation_prices enable row level security;
drop policy if exists workspace_quota_member_read on public.workspace_quota_accounts;
create policy workspace_quota_member_read on public.workspace_quota_accounts
  for select to graphytion_api using(private.graphytion_is_workspace_member(workspace_id));
drop policy if exists workspace_quota_platform_admin on public.workspace_quota_accounts;
create policy workspace_quota_platform_admin on public.workspace_quota_accounts
  for all to graphytion_api using(private.graphytion_is_platform_admin())
  with check(private.graphytion_is_platform_admin());
drop policy if exists quota_reservations_member_read on public.quota_reservations;
create policy quota_reservations_member_read on public.quota_reservations
  for select to graphytion_api using(private.graphytion_is_workspace_member(workspace_id));
drop policy if exists quota_reservations_platform_admin_read on public.quota_reservations;
create policy quota_reservations_platform_admin_read on public.quota_reservations
  for select to graphytion_api using(private.graphytion_is_platform_admin());
drop policy if exists quota_ledger_member_read on public.quota_ledger_entries;
create policy quota_ledger_member_read on public.quota_ledger_entries
  for select to graphytion_api using(private.graphytion_is_workspace_member(workspace_id));
drop policy if exists quota_ledger_platform_admin_read on public.quota_ledger_entries;
create policy quota_ledger_platform_admin_read on public.quota_ledger_entries
  for select to graphytion_api using(private.graphytion_is_platform_admin());
drop policy if exists quota_operation_prices_platform_admin on public.quota_operation_prices;
create policy quota_operation_prices_platform_admin on public.quota_operation_prices
  for all to graphytion_api using(private.graphytion_is_platform_admin())
  with check(private.graphytion_is_platform_admin());

revoke all on public.workspace_quota_accounts,public.quota_reservations,public.quota_ledger_entries,public.quota_operation_prices
  from public,anon,authenticated,service_role;
grant select,insert,update on public.workspace_quota_accounts to graphytion_api;
grant select on public.quota_reservations,public.quota_ledger_entries to graphytion_api;
grant select,insert,update on public.quota_operation_prices to graphytion_api;
revoke all on function private.graphytion_reserve_quota(uuid,uuid,text,uuid,text,bigint,jsonb) from public,anon,authenticated,service_role;
revoke all on function private.graphytion_reconcile_quota(uuid,bigint,jsonb) from public,anon,authenticated,service_role;
revoke all on function private.graphytion_release_quota(uuid,text) from public,anon,authenticated,service_role;
revoke all on function private.graphytion_reverse_quota(uuid,bigint,text,text) from public,anon,authenticated,service_role;
grant execute on function private.graphytion_reserve_quota(uuid,uuid,text,uuid,text,bigint,jsonb) to graphytion_api;
grant execute on function private.graphytion_reconcile_quota(uuid,bigint,jsonb) to graphytion_api;
grant execute on function private.graphytion_release_quota(uuid,text) to graphytion_api;
grant execute on function private.graphytion_reverse_quota(uuid,bigint,text,text) to graphytion_api;

commit;
