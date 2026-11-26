-- Graphytion Phase 03: versioned creative artifacts.
-- Additive only. Commit the migration; apply to Supabase production only with separate authorization.
begin;

create table if not exists public.creative_briefs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  project_id uuid not null references public.video_projects(id) on delete cascade,
  version integer not null check (version > 0),
  input_prompt text not null check (char_length(btrim(input_prompt)) between 1 and 20000),
  normalized_brief jsonb not null,
  source_references jsonb not null default '[]'::jsonb,
  status text not null default 'draft' check (status in ('draft','approved','superseded')),
  approved_by uuid references public.profiles(id),
  approved_at timestamptz,
  created_by uuid not null references public.profiles(id),
  created_at timestamptz not null default now(),
  unique(project_id, version),
  unique(id, project_id, workspace_id)
);
create index if not exists creative_briefs_project_version_idx
  on public.creative_briefs(project_id, version desc);

create table if not exists public.video_scripts (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  project_id uuid not null references public.video_projects(id) on delete cascade,
  brief_id uuid references public.creative_briefs(id),
  version integer not null check (version > 0),
  language text not null,
  title text not null check (char_length(btrim(title)) between 1 and 240),
  hook text,
  body jsonb not null,
  cta text,
  estimated_duration_ms integer check (estimated_duration_ms is null or estimated_duration_ms > 0),
  word_count integer check (word_count is null or word_count >= 0),
  status text not null default 'draft' check (status in ('draft','approved','superseded')),
  created_by_agent text,
  created_by uuid not null references public.profiles(id),
  created_at timestamptz not null default now(),
  unique(project_id, version),
  unique(id, project_id, workspace_id),
  foreign key (brief_id, project_id, workspace_id)
    references public.creative_briefs(id, project_id, workspace_id)
);
create index if not exists video_scripts_project_version_idx
  on public.video_scripts(project_id, version desc);

create table if not exists public.storyboards (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  project_id uuid not null references public.video_projects(id) on delete cascade,
  script_id uuid not null,
  version integer not null check (version > 0),
  global_visual_direction jsonb not null default '{}'::jsonb,
  status text not null default 'draft' check (status in ('draft','approved','superseded')),
  created_by uuid not null references public.profiles(id),
  created_at timestamptz not null default now(),
  unique(project_id, version),
  unique(id, project_id, workspace_id),
  foreign key (script_id, project_id, workspace_id)
    references public.video_scripts(id, project_id, workspace_id)
);
create index if not exists storyboards_project_version_idx
  on public.storyboards(project_id, version desc);

create table if not exists public.storyboard_scenes (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  project_id uuid not null references public.video_projects(id) on delete cascade,
  storyboard_id uuid not null,
  scene_index integer not null check (scene_index >= 0),
  title text not null check (char_length(btrim(title)) between 1 and 240),
  purpose text,
  narration_text text,
  duration_ms integer not null check (duration_ms > 0),
  visual_direction jsonb not null default '{}'::jsonb,
  transition_in text,
  transition_out text,
  motion_plan jsonb not null default '{}'::jsonb,
  asset_requirements jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(storyboard_id, scene_index),
  unique(id, project_id, workspace_id),
  foreign key (storyboard_id, project_id, workspace_id)
    references public.storyboards(id, project_id, workspace_id) on delete cascade
);
create index if not exists storyboard_scenes_order_idx
  on public.storyboard_scenes(storyboard_id, scene_index);

create table if not exists public.artifact_versions (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  project_id uuid not null references public.video_projects(id) on delete cascade,
  artifact_type text not null check (artifact_type in ('creative_brief','video_script','storyboard','storyboard_scene')),
  artifact_id uuid not null,
  version integer not null check (version > 0),
  content_hash text not null check (content_hash ~ '^[a-f0-9]{64}$'),
  created_by uuid references public.profiles(id),
  created_by_agent text,
  change_summary text,
  snapshot jsonb not null,
  created_at timestamptz not null default now(),
  unique(project_id, artifact_type, artifact_id, version)
);
create index if not exists artifact_versions_project_created_idx
  on public.artifact_versions(project_id, created_at desc);

create trigger storyboard_scenes_touch_updated_at
before update on public.storyboard_scenes
for each row execute function public.graphytion_touch_updated_at();

alter table public.creative_briefs enable row level security;
alter table public.video_scripts enable row level security;
alter table public.storyboards enable row level security;
alter table public.storyboard_scenes enable row level security;
alter table public.artifact_versions enable row level security;

drop policy if exists creative_briefs_api_tenant on public.creative_briefs;
create policy creative_briefs_api_tenant on public.creative_briefs
  for all to graphytion_api
  using (public.graphytion_is_workspace_member(workspace_id))
  with check (public.graphytion_is_workspace_member(workspace_id));

drop policy if exists video_scripts_api_tenant on public.video_scripts;
create policy video_scripts_api_tenant on public.video_scripts
  for all to graphytion_api
  using (public.graphytion_is_workspace_member(workspace_id))
  with check (public.graphytion_is_workspace_member(workspace_id));

drop policy if exists storyboards_api_tenant on public.storyboards;
create policy storyboards_api_tenant on public.storyboards
  for all to graphytion_api
  using (public.graphytion_is_workspace_member(workspace_id))
  with check (public.graphytion_is_workspace_member(workspace_id));

drop policy if exists storyboard_scenes_api_tenant on public.storyboard_scenes;
create policy storyboard_scenes_api_tenant on public.storyboard_scenes
  for all to graphytion_api
  using (public.graphytion_is_workspace_member(workspace_id))
  with check (public.graphytion_is_workspace_member(workspace_id));

drop policy if exists artifact_versions_api_tenant on public.artifact_versions;
create policy artifact_versions_api_tenant on public.artifact_versions
  for all to graphytion_api
  using (public.graphytion_is_workspace_member(workspace_id))
  with check (public.graphytion_is_workspace_member(workspace_id));

revoke all on public.creative_briefs, public.video_scripts, public.storyboards,
  public.storyboard_scenes, public.artifact_versions from public, anon, authenticated, service_role;
grant select, insert, update, delete on public.creative_briefs, public.video_scripts,
  public.storyboards, public.storyboard_scenes, public.artifact_versions to graphytion_api;

commit;
