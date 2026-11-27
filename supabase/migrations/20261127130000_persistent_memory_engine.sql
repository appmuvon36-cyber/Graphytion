-- Graphytion persistent conversation and memory foundation.
-- Additive, data-preserving; no existing rows are altered or removed.

create unique index if not exists video_projects_id_workspace_uidx
  on public.video_projects(id, workspace_id);

create table if not exists public.conversation_threads (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  project_id uuid,
  owner_user_id uuid not null references public.profiles(id) on delete cascade,
  title text not null default 'New conversation'
    check (char_length(btrim(title)) between 1 and 180),
  status text not null default 'active' check (status in ('active','archived')),
  metadata jsonb not null default '{}'::jsonb,
  last_message_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint conversation_threads_project_workspace_fk
    foreign key (project_id, workspace_id)
    references public.video_projects(id, workspace_id)
);

create table if not exists public.conversation_messages (
  id uuid primary key default gen_random_uuid(),
  thread_id uuid not null references public.conversation_threads(id) on delete cascade,
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  owner_user_id uuid not null references public.profiles(id) on delete cascade,
  sequence_no bigint not null check (sequence_no > 0),
  role text not null check (role in ('system','user','assistant','tool')),
  content text not null check (char_length(content) <= 100000),
  metadata jsonb not null default '{}'::jsonb,
  provenance jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  unique (thread_id, sequence_no)
);

create table if not exists public.memory_items (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  project_id uuid,
  owner_user_id uuid not null references public.profiles(id) on delete cascade,
  scope text not null check (scope in ('personal','project')),
  memory_type text not null check (
    memory_type in ('preference','context','fact','decision','episodic','procedural')
  ),
  title text not null check (char_length(btrim(title)) between 1 and 180),
  content text not null check (char_length(btrim(content)) between 1 and 20000),
  source_type text not null check (
    source_type in ('conversation','project','user_input','agent_output','import')
  ),
  source_id text,
  provenance jsonb not null default '{}'::jsonb,
  tags text[] not null default '{}',
  importance numeric(4,3) not null default 0.5 check (importance between 0 and 1),
  confidence numeric(4,3) not null default 1 check (confidence between 0 and 1),
  retention_policy text not null default 'until_deleted'
    check (retention_policy in ('until_deleted','expires')),
  expires_at timestamptz,
  last_accessed_at timestamptz,
  access_count bigint not null default 0 check (access_count >= 0),
  deleted_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint memory_items_scope_project_check check (
    (scope='personal' and project_id is null) or
    (scope='project' and project_id is not null)
  ),
  constraint memory_items_expiration_check check (
    (retention_policy='until_deleted' and expires_at is null) or
    (retention_policy='expires' and expires_at is not null)
  ),
  constraint memory_items_project_workspace_fk
    foreign key (project_id, workspace_id)
    references public.video_projects(id, workspace_id)
);

create index if not exists conversation_threads_owner_recent_idx
  on public.conversation_threads(workspace_id, owner_user_id, last_message_at desc nulls last);
create index if not exists conversation_threads_project_idx
  on public.conversation_threads(project_id, created_at desc) where project_id is not null;
create index if not exists conversation_messages_thread_sequence_idx
  on public.conversation_messages(thread_id, sequence_no desc);
create index if not exists memory_items_workspace_scope_recent_idx
  on public.memory_items(workspace_id, scope, updated_at desc) where deleted_at is null;
create index if not exists memory_items_project_recent_idx
  on public.memory_items(project_id, importance desc, updated_at desc)
  where deleted_at is null and project_id is not null;
create index if not exists memory_items_owner_recent_idx
  on public.memory_items(owner_user_id, importance desc, updated_at desc) where deleted_at is null;

alter table public.conversation_threads enable row level security;
alter table public.conversation_messages enable row level security;
alter table public.memory_items enable row level security;

drop policy if exists conversation_threads_api_owner on public.conversation_threads;
create policy conversation_threads_api_owner on public.conversation_threads
for all to graphytion_api, graphytion_runtime
using (owner_user_id=(select auth.uid()) and private.graphytion_is_workspace_member(workspace_id))
with check (owner_user_id=(select auth.uid()) and private.graphytion_is_workspace_member(workspace_id));

drop policy if exists conversation_messages_api_owner on public.conversation_messages;
create policy conversation_messages_api_owner on public.conversation_messages
for all to graphytion_api, graphytion_runtime
using (
  owner_user_id=(select auth.uid()) and exists (
    select 1 from public.conversation_threads t
    where t.id=thread_id and t.workspace_id=workspace_id
      and t.owner_user_id=(select auth.uid())
      and private.graphytion_is_workspace_member(t.workspace_id)
  )
)
with check (
  owner_user_id=(select auth.uid()) and exists (
    select 1 from public.conversation_threads t
    where t.id=thread_id and t.workspace_id=workspace_id
      and t.owner_user_id=(select auth.uid())
      and private.graphytion_is_workspace_member(t.workspace_id)
  )
);

drop policy if exists memory_items_api_select on public.memory_items;
create policy memory_items_api_select on public.memory_items
for select to graphytion_api, graphytion_runtime
using (
  deleted_at is null and (expires_at is null or expires_at>now())
  and private.graphytion_is_workspace_member(workspace_id)
  and (scope='project' or owner_user_id=(select auth.uid()))
);

drop policy if exists memory_items_api_insert on public.memory_items;
create policy memory_items_api_insert on public.memory_items
for insert to graphytion_api, graphytion_runtime
with check (
  owner_user_id=(select auth.uid())
  and private.graphytion_is_workspace_member(workspace_id)
  and ((scope='personal' and project_id is null) or (scope='project' and project_id is not null))
);

drop policy if exists memory_items_api_update on public.memory_items;
create policy memory_items_api_update on public.memory_items
for update to graphytion_api, graphytion_runtime
using (owner_user_id=(select auth.uid()) and private.graphytion_is_workspace_member(workspace_id))
with check (owner_user_id=(select auth.uid()) and private.graphytion_is_workspace_member(workspace_id));

grant select, insert, update, delete on public.conversation_threads,
  public.conversation_messages, public.memory_items to graphytion_api, graphytion_runtime;

comment on table public.conversation_threads is
  'Persistent user-owned conversation containers scoped to a Graphytion workspace and optional project.';
comment on table public.conversation_messages is
  'Ordered persistent conversation history with structured provenance.';
comment on table public.memory_items is
  'Personal and project-scoped persistent memory with provenance, relevance and retention metadata.';
