-- Dynamic, database-backed Agent Tool Registry and scoped permission lifecycle.
begin;

create table if not exists public.agent_tool_registry (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid references public.workspaces(id) on delete cascade,
  tool_key text not null check (tool_key ~ '^[a-z][a-z0-9_.-]{2,127}$'),
  agent_key text not null check (agent_key ~ '^[a-z][a-z0-9_.-]{1,95}$'),
  stage text not null check (stage in ('brief','script','storyboard','scene')),
  handler_key text not null check (handler_key in (
    'creative.generate_brief','creative.write_script',
    'creative.create_storyboard','creative.regenerate_scene'
  )),
  description text not null check (char_length(description) between 1 and 500),
  permission_key text not null default 'project.update',
  input_schema jsonb not null default '{"type":"object","additionalProperties":false}'::jsonb,
  configuration jsonb not null default '{}'::jsonb,
  is_active boolean not null default true,
  version integer not null default 1 check (version > 0),
  created_by uuid references auth.users(id) on delete set null,
  updated_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create unique index if not exists agent_tool_registry_global_key_uq
  on public.agent_tool_registry(tool_key) where workspace_id is null;
create unique index if not exists agent_tool_registry_workspace_key_uq
  on public.agent_tool_registry(workspace_id,tool_key) where workspace_id is not null;
create index if not exists agent_tool_registry_discovery_idx
  on public.agent_tool_registry(workspace_id,stage,is_active);

create table if not exists public.agent_tool_permissions (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  principal_type text not null check (principal_type in ('user','workspace','agent','tool','resource')),
  principal_id text not null check (char_length(principal_id) between 1 and 180),
  tool_key text,
  permission_key text not null check (char_length(permission_key) between 1 and 100),
  effect text not null check (effect in ('allow','deny')),
  resource_id text,
  valid_from timestamptz not null default now(),
  expires_at timestamptz,
  revoked_at timestamptz,
  created_by uuid not null references auth.users(id) on delete restrict,
  updated_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (expires_at is null or expires_at > valid_from)
);
create index if not exists agent_tool_permissions_lookup_idx
  on public.agent_tool_permissions(workspace_id,tool_key,principal_type,principal_id)
  where revoked_at is null;

create table if not exists public.agent_tool_audit_events (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid references public.workspaces(id) on delete cascade,
  actor_user_id uuid references auth.users(id) on delete set null,
  tool_key text,
  action text not null check (char_length(action) between 1 and 100),
  resource_id text,
  request_id text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists agent_tool_audit_events_workspace_created_idx
  on public.agent_tool_audit_events(workspace_id,created_at desc);

alter table public.agent_tool_registry enable row level security;
alter table public.agent_tool_permissions enable row level security;
alter table public.agent_tool_audit_events enable row level security;

drop policy if exists agent_tool_registry_api_read on public.agent_tool_registry;
create policy agent_tool_registry_api_read on public.agent_tool_registry
  for select to graphytion_api
  using (workspace_id is null or private.graphytion_is_workspace_member(workspace_id));
drop policy if exists agent_tool_registry_admin_write on public.agent_tool_registry;
create policy agent_tool_registry_admin_write on public.agent_tool_registry
  for all to graphytion_api
  using (private.graphytion_is_platform_admin())
  with check (private.graphytion_is_platform_admin());

drop policy if exists agent_tool_permissions_workspace_read on public.agent_tool_permissions;
create policy agent_tool_permissions_workspace_read on public.agent_tool_permissions
  for select to graphytion_api
  using (private.graphytion_is_workspace_member(workspace_id));
drop policy if exists agent_tool_permissions_admin_write on public.agent_tool_permissions;
create policy agent_tool_permissions_admin_write on public.agent_tool_permissions
  for all to graphytion_api
  using (private.graphytion_is_platform_admin())
  with check (private.graphytion_is_platform_admin());

drop policy if exists agent_tool_audit_workspace_read on public.agent_tool_audit_events;
create policy agent_tool_audit_workspace_read on public.agent_tool_audit_events
  for select to graphytion_api
  using (workspace_id is null or private.graphytion_is_workspace_member(workspace_id));
drop policy if exists agent_tool_audit_api_insert on public.agent_tool_audit_events;
create policy agent_tool_audit_api_insert on public.agent_tool_audit_events
  for insert to graphytion_api with check (
    workspace_id is null or private.graphytion_is_workspace_member(workspace_id)
  );

revoke all on public.agent_tool_registry,public.agent_tool_permissions,public.agent_tool_audit_events
  from public,anon,authenticated,service_role;
grant select,insert,update on public.agent_tool_registry to graphytion_api;
grant select,insert,update on public.agent_tool_permissions to graphytion_api;
grant select,insert on public.agent_tool_audit_events to graphytion_api;

commit;
