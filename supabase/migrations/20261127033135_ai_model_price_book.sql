-- Versioned provider/model price book and actual-token cost reconciliation.
-- Unknown or incomplete provider usage remains explicitly unpriced.
begin;
create table if not exists public.ai_model_prices (
  id uuid primary key default gen_random_uuid(),
  provider_key text not null check (provider_key ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
  model_key text not null check (model_key ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'),
  input_microusd_per_million bigint not null check (input_microusd_per_million >= 0),
  output_microusd_per_million bigint not null check (output_microusd_per_million >= 0),
  effective_at timestamptz not null default now(),
  is_active boolean not null default true,
  notes text,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  unique(provider_key,model_key,effective_at)
);
create index if not exists ai_model_prices_lookup_idx
  on public.ai_model_prices(provider_key,model_key,effective_at desc) where is_active=true;
alter table public.ai_usage_events
  add column if not exists pricing_id uuid references public.ai_model_prices(id) on delete set null,
  add column if not exists input_cost_microusd bigint,
  add column if not exists output_cost_microusd bigint,
  add column if not exists total_cost_microusd bigint,
  add column if not exists cost_currency text not null default 'USD',
  add column if not exists cost_status text not null default 'unpriced'
    check (cost_status in ('priced','unpriced'));
alter table public.ai_model_prices enable row level security;
drop policy if exists ai_model_prices_platform_admin on public.ai_model_prices;
create policy ai_model_prices_platform_admin on public.ai_model_prices
  for all to graphytion_api using (private.graphytion_is_platform_admin())
  with check (private.graphytion_is_platform_admin());
revoke all on public.ai_model_prices from public,anon,authenticated,service_role;
grant select,insert,update on public.ai_model_prices to graphytion_api;
create or replace function private.graphytion_price_ai_usage_event()
returns trigger language plpgsql security definer set search_path = ''
as $$
declare selected_price record;
begin
  select id,input_microusd_per_million,output_microusd_per_million into selected_price
  from public.ai_model_prices
  where provider_key=new.provider_key and model_key=new.model_key
    and effective_at <= coalesce(new.created_at,now())
  order by effective_at desc,created_at desc limit 1;
  if not found or new.input_tokens is null or new.output_tokens is null then
    new.pricing_id := null;
    new.input_cost_microusd := null;
    new.output_cost_microusd := null;
    new.total_cost_microusd := null;
    new.cost_currency := 'USD';
    new.cost_status := 'unpriced';
  else
    new.pricing_id := selected_price.id;
    new.input_cost_microusd := round(new.input_tokens::numeric *
      selected_price.input_microusd_per_million / 1000000)::bigint;
    new.output_cost_microusd := round(new.output_tokens::numeric *
      selected_price.output_microusd_per_million / 1000000)::bigint;
    new.total_cost_microusd := new.input_cost_microusd + new.output_cost_microusd;
    new.cost_currency := 'USD';
    new.cost_status := 'priced';
  end if;
  return new;
end;
$$;
revoke all on function private.graphytion_price_ai_usage_event() from public,anon,authenticated,service_role;
drop trigger if exists ai_usage_events_price_before_write on public.ai_usage_events;
create trigger ai_usage_events_price_before_write
  before insert or update of provider_key,model_key,input_tokens,output_tokens
  on public.ai_usage_events for each row
  execute function private.graphytion_price_ai_usage_event();
commit;
