-- Separate media provider cost, operational overhead, quota debit and margin.
begin;

alter table public.media_generation_jobs
  add column if not exists operational_cost_microusd bigint
    check (operational_cost_microusd is null or operational_cost_microusd >= 0),
  add column if not exists quota_debit_microusd bigint
    check (quota_debit_microusd is null or quota_debit_microusd >= 0),
  add column if not exists margin_microusd bigint,
  add column if not exists economics_status text not null default 'unpriced'
    check (economics_status in ('complete','partial','unpriced'));

create table if not exists public.media_operational_cost_prices (
  id uuid primary key default gen_random_uuid(),
  media_type text not null check (media_type in ('image','video')),
  provider_key text not null check (provider_key ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
  model_key text not null check (model_key ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'),
  microusd_per_unit bigint not null check (microusd_per_unit >= 0),
  unit_name text not null check (unit_name in ('image','second')),
  effective_at timestamptz not null default now(),
  is_active boolean not null default true,
  notes text not null check (char_length(notes) between 1 and 500),
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique(media_type,provider_key,model_key,effective_at),
  check ((media_type='image' and unit_name='image') or (media_type='video' and unit_name='second'))
);
create index if not exists media_operational_cost_price_lookup_idx
  on public.media_operational_cost_prices(media_type,provider_key,model_key,effective_at desc)
  where is_active=true;

alter table public.media_operational_cost_prices enable row level security;
drop policy if exists media_operational_cost_prices_admin on public.media_operational_cost_prices;
create policy media_operational_cost_prices_admin on public.media_operational_cost_prices
  for all to graphytion_api using (private.graphytion_is_platform_admin())
  with check (private.graphytion_is_platform_admin());
revoke all on public.media_operational_cost_prices from public,anon,authenticated,service_role;
grant select,insert,update on public.media_operational_cost_prices to graphytion_api;

commit;
