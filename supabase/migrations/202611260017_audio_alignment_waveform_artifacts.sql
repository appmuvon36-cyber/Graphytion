-- Persist real provider word alignment and audio waveform analysis artifacts.
begin;

alter table public.audio_generations
  add column if not exists alignment_status text not null default 'not_requested'
    check (alignment_status in ('not_requested','available','unavailable')),
  add column if not exists alignment_result jsonb not null default '[]'::jsonb;

create table if not exists public.audio_analysis_artifacts (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  project_id uuid not null references public.video_projects(id) on delete cascade,
  audio_generation_id uuid not null references public.audio_generations(id) on delete cascade,
  audio_asset_id uuid not null references public.project_assets(id) on delete cascade,
  waveform_bucket text not null,
  waveform_path text not null,
  waveform_sha256 text not null check (waveform_sha256 ~ '^[a-f0-9]{64}$'),
  media_metadata jsonb not null,
  created_at timestamptz not null default now(),
  unique (audio_generation_id),
  unique (waveform_bucket,waveform_path)
);
create index if not exists audio_analysis_project_idx
  on public.audio_analysis_artifacts(project_id,created_at desc);

alter table public.audio_analysis_artifacts enable row level security;
drop policy if exists audio_analysis_tenant_api on public.audio_analysis_artifacts;
create policy audio_analysis_tenant_api on public.audio_analysis_artifacts for all to graphytion_api
  using (private.graphytion_is_workspace_member(workspace_id))
  with check (private.graphytion_is_workspace_member(workspace_id));

revoke all on public.audio_analysis_artifacts from public, anon, authenticated, service_role;
grant select, insert, update, delete on public.audio_analysis_artifacts to graphytion_api;
grant select, update on public.audio_generations to graphytion_api;

commit;
