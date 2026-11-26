-- Graphytion Phase 03: durable agent orchestration state.
-- Additive migration only. Do not apply to Production without separate authorization.
begin;

create table if not exists public.production_runs (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.video_projects(id) on delete cascade,
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  requested_by uuid not null references public.profiles(id),
  status text not null default 'queued'
    check (status in ('queued','planning','scripting','storyboarding','ready_for_review','failed','cancel_requested','cancelled','completed')),
  current_stage text,
  progress_percent numeric(5,2) not null default 0 check (progress_percent between 0 and 100),
  input_snapshot jsonb not null,
  config_snapshot jsonb not null default '{}'::jsonb,
  idempotency_key text not null check (char_length(idempotency_key) between 16 and 128),
  error_code text,
  error_message_safe text,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(workspace_id,idempotency_key),
  unique(id,workspace_id,project_id)
);
create index if not exists production_runs_workspace_created_idx
  on public.production_runs(workspace_id,created_at desc);
create index if not exists production_runs_status_created_idx
  on public.production_runs(status,created_at);

create table if not exists public.agent_tasks (
  id uuid primary key default gen_random_uuid(),
  production_run_id uuid not null references public.production_runs(id) on delete cascade,
  parent_task_id uuid references public.agent_tasks(id),
  agent_key text not null,
  task_type text not null,
  status text not null default 'pending'
    check (status in ('pending','queued','running','succeeded','failed','retry_wait','cancelled','skipped')),
  input_artifact_id uuid,
  output_artifact_id uuid,
  input_payload jsonb not null,
  output_payload jsonb,
  prompt_version_id uuid,
  model_config_snapshot jsonb,
  attempt_count integer not null default 0 check (attempt_count >= 0),
  max_attempts integer not null default 3 check (max_attempts between 1 and 10),
  lease_expires_at timestamptz,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  error_code text,
  error_detail_internal text
);
create index if not exists agent_tasks_run_status_idx
  on public.agent_tasks(production_run_id,status,created_at);

create table if not exists public.workflow_checkpoints (
  id uuid primary key default gen_random_uuid(),
  production_run_id uuid not null references public.production_runs(id) on delete cascade,
  stage_key text not null,
  checkpoint_key text not null,
  payload jsonb not null,
  content_hash text not null check (content_hash ~ '^[a-f0-9]{64}$'),
  created_at timestamptz not null default now(),
  unique(production_run_id,checkpoint_key)
);
create table if not exists public.workflow_events (
  id uuid primary key default gen_random_uuid(),
  production_run_id uuid not null references public.production_runs(id) on delete cascade,
  event_type text not null,
  event_payload jsonb not null default '{}'::jsonb,
  sequence_number bigint not null check (sequence_number > 0),
  created_at timestamptz not null default now(),
  unique(production_run_id,sequence_number)
);
create index if not exists workflow_events_run_sequence_idx
  on public.workflow_events(production_run_id,sequence_number);

create trigger production_runs_touch_updated_at
before update on public.production_runs
for each row execute function public.graphytion_touch_updated_at();

alter table public.production_runs enable row level security;
alter table public.agent_tasks enable row level security;
alter table public.workflow_checkpoints enable row level security;
alter table public.workflow_events enable row level security;

drop policy if exists production_runs_api_tenant on public.production_runs;
create policy production_runs_api_tenant on public.production_runs
  for all to graphytion_api
  using (private.graphytion_is_workspace_member(workspace_id))
  with check (private.graphytion_is_workspace_member(workspace_id));

drop policy if exists agent_tasks_api_tenant on public.agent_tasks;
create policy agent_tasks_api_tenant on public.agent_tasks
  for all to graphytion_api
  using (exists (
    select 1 from public.production_runs r
    where r.id=production_run_id and private.graphytion_is_workspace_member(r.workspace_id)
  ))
  with check (exists (
    select 1 from public.production_runs r
    where r.id=production_run_id and private.graphytion_is_workspace_member(r.workspace_id)
  ));

drop policy if exists workflow_checkpoints_api_tenant on public.workflow_checkpoints;
create policy workflow_checkpoints_api_tenant on public.workflow_checkpoints
  for all to graphytion_api
  using (exists (
    select 1 from public.production_runs r
    where r.id=production_run_id and private.graphytion_is_workspace_member(r.workspace_id)
  ))
  with check (exists (
    select 1 from public.production_runs r
    where r.id=production_run_id and private.graphytion_is_workspace_member(r.workspace_id)
  ));

drop policy if exists workflow_events_api_tenant on public.workflow_events;
create policy workflow_events_api_tenant on public.workflow_events
  for all to graphytion_api
  using (exists (
    select 1 from public.production_runs r
    where r.id=production_run_id and private.graphytion_is_workspace_member(r.workspace_id)
  ))
  with check (exists (
    select 1 from public.production_runs r
    where r.id=production_run_id and private.graphytion_is_workspace_member(r.workspace_id)
  ));

revoke all on public.production_runs, public.agent_tasks,
  public.workflow_checkpoints, public.workflow_events from public, anon, authenticated, service_role;
grant select, insert, update, delete on public.production_runs, public.agent_tasks,
  public.workflow_checkpoints, public.workflow_events to graphytion_api;

commit;
