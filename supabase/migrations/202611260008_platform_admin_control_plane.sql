-- Platform-level administrator identity is independent from workspace roles.
-- Additive and forward-only. Do not apply to production without explicit authorization.
begin;

create table if not exists public.platform_admins (
  user_id uuid primary key references public.profiles(id) on delete restrict,
  role text not null check (role in ('super_admin','support_admin','operations_admin')),
  status text not null default 'active' check (status in ('active','revoked')),
  granted_by uuid references public.profiles(id),
  granted_at timestamptz not null default now(),
  revoked_at timestamptz,
  reason text
);

create index if not exists platform_admins_active_role_idx
  on public.platform_admins(role) where status='active';

create or replace function private.graphytion_is_platform_admin()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.platform_admins pa
    where pa.user_id = nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
      and pa.status = 'active'
  );
$$;

revoke all on function private.graphytion_is_platform_admin() from public, anon, authenticated;
grant execute on function private.graphytion_is_platform_admin() to graphytion_api;

alter table public.platform_admins enable row level security;
drop policy if exists platform_admins_platform_admin_only on public.platform_admins;
create policy platform_admins_platform_admin_only on public.platform_admins
  for select to graphytion_api using (private.graphytion_is_platform_admin());

drop policy if exists profiles_platform_admin_read on public.profiles;
create policy profiles_platform_admin_read on public.profiles
  for select to graphytion_api using (private.graphytion_is_platform_admin());

drop policy if exists workspaces_platform_admin_read on public.workspaces;
create policy workspaces_platform_admin_read on public.workspaces
  for select to graphytion_api using (private.graphytion_is_platform_admin());

drop policy if exists workspace_members_platform_admin_read on public.workspace_members;
create policy workspace_members_platform_admin_read on public.workspace_members
  for select to graphytion_api using (private.graphytion_is_platform_admin());

drop policy if exists video_projects_platform_admin_read on public.video_projects;
create policy video_projects_platform_admin_read on public.video_projects
  for select to graphytion_api using (private.graphytion_is_platform_admin());

drop policy if exists audit_logs_platform_admin_read on public.audit_logs;
create policy audit_logs_platform_admin_read on public.audit_logs
  for select to graphytion_api using (private.graphytion_is_platform_admin());
drop policy if exists audit_logs_platform_admin_insert on public.audit_logs;
create policy audit_logs_platform_admin_insert on public.audit_logs
  for insert to graphytion_api with check (private.graphytion_is_platform_admin());

revoke all on public.platform_admins from public, anon, authenticated, service_role;
grant select on public.platform_admins to graphytion_api;

commit;
