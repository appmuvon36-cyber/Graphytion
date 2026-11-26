-- Provider token usage ledger; costs are not inferred without a configured price book.
begin;

create table if not exists public.ai_usage_events (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  project_id uuid not null references public.video_projects(id) on delete cascade,
  production_run_id uuid not null references public.production_runs(id) on delete cascade,
  agent_task_id uuid not null references public.agent_tasks(id) on delete cascade,
  agent_key text not null,
  prompt_version integer not null check (prompt_version > 0),
  provider_key text not null,
  model_key text not null,
  input_tokens integer check (input_tokens is null or input_tokens >= 0),
  output_tokens integer check (output_tokens is null or output_tokens >= 0),
  provider_request_id text,
  created_at timestamptz not null default now()
);
create index if not exists ai_usage_events_workspace_created_idx
  on public.ai_usage_events(workspace_id,created_at desc);
create index if not exists ai_usage_events_run_idx
  on public.ai_usage_events(production_run_id);

alter table public.ai_usage_events enable row level security;
drop policy if exists ai_usage_events_api_tenant on public.ai_usage_events;
create policy ai_usage_events_api_tenant on public.ai_usage_events
  for all to graphytion_api
  using (private.graphytion_is_workspace_member(workspace_id))
  with check (private.graphytion_is_workspace_member(workspace_id));
drop policy if exists ai_usage_events_platform_admin_read on public.ai_usage_events;
create policy ai_usage_events_platform_admin_read on public.ai_usage_events
  for select to graphytion_api using (private.graphytion_is_platform_admin());

revoke all on public.ai_usage_events from public, anon, authenticated, service_role;
grant select,insert,update,delete on public.ai_usage_events to graphytion_api;

commit;
