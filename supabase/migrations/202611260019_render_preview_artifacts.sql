-- Keep thumbnails and preview renditions separate from final render output.
begin;
create table if not exists public.render_artifacts (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  project_id uuid not null references public.video_projects(id) on delete cascade,
  render_job_id uuid not null references public.render_jobs(id) on delete cascade,
  artifact_type text not null check (artifact_type in ('thumbnail','preview')),
  storage_bucket text not null,
  storage_path text not null,
  mime_type text not null check (mime_type in ('image/jpeg','image/png','video/mp4','video/webm')),
  size_bytes bigint not null check (size_bytes > 0),
  sha256 text not null check (sha256 ~ '^[a-f0-9]{64}$'),
  snapshot_version integer not null check (snapshot_version > 0),
  created_at timestamptz not null default now(),
  unique (render_job_id,artifact_type),
  unique (storage_bucket,storage_path)
);
create index if not exists render_artifacts_project_idx
  on public.render_artifacts(project_id,artifact_type,created_at desc);
alter table public.render_artifacts enable row level security;
drop policy if exists render_artifacts_tenant_api on public.render_artifacts;
create policy render_artifacts_tenant_api on public.render_artifacts for all to graphytion_api
  using (private.graphytion_is_workspace_member(workspace_id))
  with check (private.graphytion_is_workspace_member(workspace_id));
revoke all on public.render_artifacts from public, anon, authenticated, service_role;
grant select, insert, update, delete on public.render_artifacts to graphytion_api;
commit;
