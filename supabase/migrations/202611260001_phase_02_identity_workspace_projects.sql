-- Graphytion Phase 02: identity, tenancy, RBAC and project foundation.
-- Apply only after explicit production migration authorization.
begin;

create extension if not exists pgcrypto;

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  avatar_path text,
  bio text,
  locale text not null default 'id-ID',
  timezone text not null default 'Asia/Jakarta',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.workspaces (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(btrim(name)) between 1 and 120),
  slug text not null unique check (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
  owner_user_id uuid not null references public.profiles(id),
  plan_id uuid,
  settings jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists workspaces_owner_user_idx on public.workspaces(owner_user_id);

create table if not exists public.workspace_members (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  user_id uuid not null references public.profiles(id) on delete cascade,
  role text not null check (role in ('owner','admin','editor','member','viewer','billing')),
  status text not null default 'active' check (status in ('active','suspended','left')),
  created_at timestamptz not null default now(),
  unique (workspace_id,user_id)
);

create table if not exists public.workspace_invitations (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  email text not null,
  role text not null check (role in ('admin','editor','member','viewer','billing')),
  token_hash text not null unique,
  invited_by uuid not null references public.profiles(id),
  expires_at timestamptz not null,
  accepted_at timestamptz,
  cancelled_at timestamptz,
  created_at timestamptz not null default now(),
  constraint invitation_expiry_after_creation check (expires_at > created_at)
);
create unique index if not exists workspace_invitations_pending_email_uq
  on public.workspace_invitations(workspace_id,lower(email))
  where accepted_at is null and cancelled_at is null;
create index if not exists workspace_invitations_workspace_expiry_idx
  on public.workspace_invitations(workspace_id,expires_at);
create index if not exists workspace_invitations_invited_by_idx
  on public.workspace_invitations(invited_by);

create table if not exists public.video_projects (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  created_by uuid not null references public.profiles(id),
  name text not null check (char_length(btrim(name)) between 1 and 160),
  description text,
  production_mode text not null default 'motion_graphic'
    check (production_mode in ('motion_graphic','explainer','presentation','social_short','documentary_lite')),
  status text not null default 'draft'
    check (status in ('draft','active','archived','deleted')),
  default_language text not null default 'id-ID',
  target_duration_ms integer check (target_duration_ms is null or target_duration_ms > 0),
  aspect_ratio text not null default '16:9'
    check (aspect_ratio in ('16:9','9:16','1:1','4:5','4:3')),
  width integer not null default 1920 check (width between 1 and 16384),
  height integer not null default 1080 check (height between 1 and 16384),
  fps integer not null default 30 check (fps between 1 and 120),
  brand_kit_id uuid,
  active_run_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists video_projects_workspace_updated_idx
  on public.video_projects(workspace_id,updated_at desc) where status <> 'deleted';
create index if not exists video_projects_workspace_created_idx
  on public.video_projects(workspace_id,created_at desc) where status <> 'deleted';
create index if not exists video_projects_workspace_name_idx
  on public.video_projects(workspace_id,name) where status <> 'deleted';
create index if not exists video_projects_created_by_idx
  on public.video_projects(created_by);
create index if not exists workspace_members_user_status_idx
  on public.workspace_members(user_id,status,workspace_id);

create table if not exists public.project_settings (
  project_id uuid primary key references public.video_projects(id) on delete cascade,
  settings jsonb not null default '{}'::jsonb,
  version integer not null default 1 check (version > 0),
  updated_at timestamptz not null default now()
);

create table if not exists public.api_idempotency_keys (
  id uuid primary key default gen_random_uuid(),
  actor_user_id uuid not null references public.profiles(id) on delete cascade,
  operation text not null,
  idempotency_key text not null check (char_length(idempotency_key) between 16 and 128),
  request_hash text not null check (request_hash ~ '^[a-f0-9]{64}$'),
  response_body jsonb,
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  expires_at timestamptz not null default (now() + interval '24 hours'),
  unique (actor_user_id,operation,idempotency_key)
);
create index if not exists api_idempotency_expiry_idx
  on public.api_idempotency_keys(expires_at);

create table if not exists public.audit_logs (
  id uuid primary key default gen_random_uuid(),
  actor_user_id uuid references public.profiles(id) on delete set null,
  workspace_id uuid references public.workspaces(id) on delete set null,
  action text not null,
  resource_type text not null,
  resource_id uuid,
  metadata jsonb not null default '{}'::jsonb,
  request_id text,
  created_at timestamptz not null default now()
);
create index if not exists audit_logs_workspace_created_idx
  on public.audit_logs(workspace_id,created_at desc);
create index if not exists audit_logs_actor_created_idx
  on public.audit_logs(actor_user_id,created_at desc);

create or replace function public.graphytion_touch_updated_at()
returns trigger language plpgsql set search_path = public as $$
begin
  new.updated_at = now();
  return new;
end
$$;

drop trigger if exists profiles_touch_updated_at on public.profiles;
create trigger profiles_touch_updated_at before update on public.profiles
for each row execute function public.graphytion_touch_updated_at();
drop trigger if exists workspaces_touch_updated_at on public.workspaces;
create trigger workspaces_touch_updated_at before update on public.workspaces
for each row execute function public.graphytion_touch_updated_at();
drop trigger if exists video_projects_touch_updated_at on public.video_projects;
create trigger video_projects_touch_updated_at before update on public.video_projects
for each row execute function public.graphytion_touch_updated_at();

create or replace function public.graphytion_sync_auth_profile()
returns trigger language plpgsql security definer set search_path = public, auth as $$
begin
  insert into public.profiles(id,display_name)
  values (
    new.id,
    nullif(btrim(coalesce(new.raw_user_meta_data->>'display_name',new.raw_user_meta_data->>'full_name','')), '')
  )
  on conflict (id) do update set
    display_name = coalesce(public.profiles.display_name,excluded.display_name),
    updated_at = now();
  return new;
end
$$;
drop trigger if exists graphytion_auth_user_profile on auth.users;
create trigger graphytion_auth_user_profile after insert on auth.users
for each row execute function public.graphytion_sync_auth_profile();

-- Backfill profiles for existing Auth users without changing existing profile values.
insert into public.profiles(id,display_name)
select
  u.id,
  nullif(btrim(coalesce(u.raw_user_meta_data->>'display_name',u.raw_user_meta_data->>'full_name','')), '')
from auth.users u
on conflict (id) do update set
  display_name = coalesce(public.profiles.display_name,excluded.display_name),
  updated_at = now();

create or replace function public.graphytion_is_workspace_member(target_workspace uuid)
returns boolean language sql stable security definer set search_path = public, auth as $$
  select exists (
    select 1 from public.workspace_members m
    where m.workspace_id=target_workspace
      and m.user_id=auth.uid()
      and m.status='active'
  )
$$;

create or replace function public.graphytion_workspace_role(target_workspace uuid)
returns text language sql stable security definer set search_path = public, auth as $$
  select m.role from public.workspace_members m
  where m.workspace_id=target_workspace
    and m.user_id=auth.uid()
    and m.status='active'
  limit 1
$$;

create or replace function public.graphytion_workspace_owner(target_workspace uuid)
returns uuid language sql stable security definer set search_path = public, auth as $graphytion$
  select w.owner_user_id
  from public.workspaces w
  where w.id=target_workspace
    and exists (
      select 1 from public.workspace_members m
      where m.workspace_id=target_workspace
        and m.user_id=auth.uid()
        and m.status='active'
    )
$graphytion$;

create or replace function public.graphytion_protect_workspace_owner()
returns trigger language plpgsql set search_path = public as $$
begin
  if new.owner_user_id <> old.owner_user_id then
    raise exception 'workspace ownership transfer requires a dedicated workflow'
      using errcode = '42501';
  end if;
  return new;
end
$$;
drop trigger if exists workspaces_protect_owner on public.workspaces;
create trigger workspaces_protect_owner before update on public.workspaces
for each row execute function public.graphytion_protect_workspace_owner();

create or replace function public.graphytion_protect_membership_identity()
returns trigger language plpgsql set search_path = public as $$
begin
  if new.workspace_id <> old.workspace_id or new.user_id <> old.user_id then
    raise exception 'workspace membership identity is immutable' using errcode = '42501';
  end if;
  if old.role = 'owner' and new.role <> 'owner' then
    raise exception 'workspace ownership must be transferred explicitly' using errcode = '42501';
  end if;
  if new.role = 'owner' and old.role <> 'owner' then
    raise exception 'workspace ownership must be transferred explicitly' using errcode = '42501';
  end if;
  return new;
end
$$;
drop trigger if exists workspace_members_protect_identity on public.workspace_members;
create trigger workspace_members_protect_identity before update on public.workspace_members
for each row execute function public.graphytion_protect_membership_identity();

-- Keep SECURITY DEFINER helpers private to authenticated callers and avoid exposing trigger functions as RPCs.
revoke all on function public.graphytion_sync_auth_profile() from public, anon, authenticated;
revoke all on function public.graphytion_touch_updated_at() from public, anon, authenticated;
revoke all on function public.graphytion_protect_workspace_owner() from public, anon, authenticated;
revoke all on function public.graphytion_protect_membership_identity() from public, anon, authenticated;
revoke all on function public.graphytion_is_workspace_member(uuid) from public, anon, authenticated;
revoke all on function public.graphytion_workspace_role(uuid) from public, anon, authenticated;
revoke all on function public.graphytion_workspace_owner(uuid) from public, anon, authenticated;
grant execute on function public.graphytion_is_workspace_member(uuid) to authenticated;
grant execute on function public.graphytion_workspace_role(uuid) to authenticated;
grant execute on function public.graphytion_workspace_owner(uuid) to authenticated;

create or replace function public.graphytion_protect_project_tenant()
returns trigger language plpgsql set search_path = public as $$
begin
  if new.workspace_id <> old.workspace_id or new.created_by <> old.created_by then
    raise exception 'project tenant and creator are immutable' using errcode = '42501';
  end if;
  return new;
end
$;
revoke all on function public.graphytion_protect_project_tenant() from public, anon, authenticated;
drop trigger if exists video_projects_protect_tenant on public.video_projects;
create trigger video_projects_protect_tenant before update on public.video_projects
for each row execute function public.graphytion_protect_project_tenant();

alter table public.profiles enable row level security;
alter table public.workspaces enable row level security;
alter table public.workspace_members enable row level security;
alter table public.workspace_invitations enable row level security;
alter table public.video_projects enable row level security;
alter table public.project_settings enable row level security;
alter table public.api_idempotency_keys enable row level security;
alter table public.audit_logs enable row level security;

-- Explicit Data API privileges: this project uses FastAPI as the only write path.
-- Authenticated clients receive only the read/update privileges covered by RLS.
grant usage on schema public to authenticated, service_role;
grant select on public.profiles, public.workspaces, public.workspace_members,
  public.video_projects, public.project_settings, public.audit_logs to authenticated;
grant update on public.workspaces to authenticated;
grant all privileges on public.profiles, public.workspaces, public.workspace_members,
  public.workspace_invitations, public.video_projects, public.project_settings,
  public.api_idempotency_keys, public.audit_logs to service_role;

drop policy if exists profiles_select_self on public.profiles;
create policy profiles_select_self on public.profiles for select to authenticated
using (id=auth.uid());
drop policy if exists profiles_update_self on public.profiles;
create policy profiles_update_self on public.profiles for update to authenticated
using (id=auth.uid()) with check (id=auth.uid());

-- Prevent direct clients from changing server-managed avatar paths or identity keys.
revoke update on table public.profiles from anon, authenticated;
grant update (display_name,bio,locale,timezone) on table public.profiles to authenticated;

drop policy if exists workspaces_select_member on public.workspaces;
create policy workspaces_select_member on public.workspaces for select to authenticated
using (public.graphytion_is_workspace_member(id));
drop policy if exists workspaces_update_admin on public.workspaces;
create policy workspaces_update_admin on public.workspaces for update to authenticated
using (public.graphytion_workspace_role(id) in ('owner','admin'))
with check (
  public.graphytion_workspace_role(id) in ('owner','admin')
  and owner_user_id=public.graphytion_workspace_owner(id)
);

drop policy if exists workspace_members_select_member on public.workspace_members;
create policy workspace_members_select_member on public.workspace_members for select to authenticated
using (public.graphytion_workspace_role(workspace_id) in ('owner','admin','editor','member'));
-- Membership writes are server-only; no authenticated direct-write policy is granted.

-- Invitation reads and writes are server-only and mediated by FastAPI.

drop policy if exists video_projects_member_select on public.video_projects;
create policy video_projects_member_select on public.video_projects for select to authenticated
using (
  public.graphytion_workspace_role(workspace_id) in ('owner','admin','editor','member','viewer')
  and status <> 'deleted'
);
-- Project mutations are server-only; FastAPI permission checks remain authoritative.

drop policy if exists project_settings_member_select on public.project_settings;
create policy project_settings_member_select on public.project_settings for select to authenticated
using (
  exists (
    select 1 from public.video_projects p
    where p.id=project_id
      and public.graphytion_workspace_role(p.workspace_id) in ('owner','admin','editor','member','viewer')
  )
);
-- Project settings mutations are server-only.

drop policy if exists audit_logs_workspace_read on public.audit_logs;
create policy audit_logs_workspace_read on public.audit_logs for select to authenticated
using (
  workspace_id is not null
  and public.graphytion_workspace_role(workspace_id) in ('owner','admin')
);
-- Idempotency records have no authenticated policies and remain server-only.

-- Provision a private avatar bucket without silently changing an existing bucket.
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values ('avatars','avatars',false,5242880,array['image/png','image/jpeg','image/webp'])
on conflict (id) do nothing;

do $avatars$
begin
  if exists (
    select 1 from storage.buckets
    where id='avatars'
      and (
        public
        or file_size_limit is distinct from 5242880
        or allowed_mime_types is distinct from array['image/png','image/jpeg','image/webp']
      )
  ) then
    raise exception 'Existing avatars bucket configuration is incompatible; reconcile it before migration';
  end if;
end
$avatars$;

drop policy if exists graphytion_avatar_read_own on storage.objects;
create policy graphytion_avatar_read_own on storage.objects for select to authenticated
using (bucket_id='avatars' and (storage.foldername(name))[1]=auth.uid()::text);
drop policy if exists graphytion_avatar_insert_own on storage.objects;
create policy graphytion_avatar_insert_own on storage.objects for insert to authenticated
with check (bucket_id='avatars' and (storage.foldername(name))[1]=auth.uid()::text);
drop policy if exists graphytion_avatar_delete_own on storage.objects;
create policy graphytion_avatar_delete_own on storage.objects for delete to authenticated
using (bucket_id='avatars' and (storage.foldername(name))[1]=auth.uid()::text);

commit;
