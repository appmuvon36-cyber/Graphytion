-- Runtime must read effective price books under the authenticated workspace subject.
-- Writes remain restricted to platform administrators.
begin;

drop policy if exists ai_model_prices_api_read on public.ai_model_prices;
create policy ai_model_prices_api_read on public.ai_model_prices
  for select to graphytion_api using (true);

drop policy if exists quota_operation_prices_api_read on public.quota_operation_prices;
create policy quota_operation_prices_api_read on public.quota_operation_prices
  for select to graphytion_api using (true);

drop policy if exists media_operational_cost_prices_api_read on public.media_operational_cost_prices;
create policy media_operational_cost_prices_api_read on public.media_operational_cost_prices
  for select to graphytion_api using (true);

commit;
