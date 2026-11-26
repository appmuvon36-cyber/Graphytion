-- Tenant-owned private project asset storage metadata.
begin;

insert into storage.buckets(id,name,public)
values ('project-assets','project-assets',false)
on conflict (id) do update set public=false;

create table if not exists public.project_assets (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  project_id uuid not null references public.video_projects(id) on delete cascade,
  uploaded_by uuid not null references public.profiles(id),
  bucket text not null default 'project-assets',
  object_path text not null unique,
  file_name text not null,
  content_type text not null,
  size_bytes bigint not null check (size_bytes > 0 and size_bytes <= 52428800),
  sha256 text not null check (sha256 ~ '^[a-f0-9]{64}$'),
  status text not null default 'active' check (status in ('active','deleting','delete_failed','deleted')),
  deleted_at timestamptz,
  created_at timestamptz not null default now(),
  unique(id,project_id,workspace_id)
);
create index if not exists project_assets_project_created_idx
  on public.project_assets(project_id,created_at desc)
  where status='active';

alter table public.project_assets enable row level security;
drop policy if exists project_assets_api_tenant on public.project_assets;
create policy project_assets_api_tenant on public.project_assets
  for all to graphytion_api
  using (private.graphytion_is_workspace_member(workspace_id))
  with check (private.graphytion_is_workspace_member(workspace_id));
drop policy if exists project_assets_platform_admin_read on public.project_assets;
create policy project_assets_platform_admin_read on public.project_assets
  for select to graphytion_api using (private.graphytion_is_platform_admin());

revoke all on public.project_assets from public, anon, authenticated, service_role;
grant select,insert,update,delete on public.project_assets to graphytion_api;

commit;
