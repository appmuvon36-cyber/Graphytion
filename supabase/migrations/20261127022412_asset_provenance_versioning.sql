-- Asset provenance, family versioning and cross-project workspace library metadata.
begin;

alter table public.project_assets
  add column if not exists asset_family_id uuid not null default gen_random_uuid(),
  add column if not exists version_number integer not null default 1
    check (version_number > 0),
  add column if not exists supersedes_asset_id uuid
    references public.project_assets(id) on delete set null,
  add column if not exists source_type text not null default 'upload'
    check (source_type in ('upload','generated','external','stock','system')),
  add column if not exists source_provider text,
  add column if not exists source_job_id uuid
    references public.media_generation_jobs(id) on delete set null,
  add column if not exists provenance jsonb not null default '{}'::jsonb,
  add column if not exists usage_rights_status text not null default 'unverified'
    check (usage_rights_status in ('unverified','verified','restricted','expired')),
  add column if not exists license_type text,
  add column if not exists commercial_use_allowed boolean,
  add column if not exists attribution text;

create unique index if not exists project_assets_family_version_uq
  on public.project_assets(asset_family_id,version_number);
create index if not exists project_assets_workspace_library_idx
  on public.project_assets(workspace_id,status,created_at desc)
  where status='active';
create index if not exists project_assets_source_job_idx
  on public.project_assets(source_job_id) where source_job_id is not null;

commit;
