-- Add FK-supporting indexes for media generation and generated asset lifecycle.
-- Safe, additive, and data-preserving. No quota reservation/debit behavior is changed.
begin;

create index if not exists media_generation_requested_by_idx
  on public.media_generation_jobs(requested_by);
create index if not exists media_generation_asset_id_idx
  on public.media_generation_jobs(asset_id) where asset_id is not null;
create index if not exists media_generation_quota_reservation_idx
  on public.media_generation_jobs(quota_reservation_id) where quota_reservation_id is not null;
create index if not exists media_generation_quota_price_idx
  on public.media_generation_jobs(quota_price_id) where quota_price_id is not null;
create index if not exists media_generation_operational_price_idx
  on public.media_generation_jobs(operational_price_id) where operational_price_id is not null;
create index if not exists media_generation_provider_price_idx
  on public.media_generation_jobs(provider_price_id) where provider_price_id is not null;

create index if not exists project_assets_uploaded_by_idx
  on public.project_assets(uploaded_by);
create index if not exists project_assets_supersedes_asset_idx
  on public.project_assets(supersedes_asset_id) where supersedes_asset_id is not null;

commit;
