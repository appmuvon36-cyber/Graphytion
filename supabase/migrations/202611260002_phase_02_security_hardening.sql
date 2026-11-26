-- Graphytion Phase 02 follow-up: keep SECURITY DEFINER RLS helpers out of exposed public schema.
begin;

create schema if not exists private;
revoke all on schema private from public, anon;
grant usage on schema private to authenticated;

alter function public.graphytion_is_workspace_member(uuid) set schema private;
alter function public.graphytion_workspace_role(uuid) set schema private;
alter function public.graphytion_workspace_owner(uuid) set schema private;

revoke all on function private.graphytion_is_workspace_member(uuid) from public, anon, authenticated;
revoke all on function private.graphytion_workspace_role(uuid) from public, anon, authenticated;
revoke all on function private.graphytion_workspace_owner(uuid) from public, anon, authenticated;
grant execute on function private.graphytion_is_workspace_member(uuid) to authenticated;
grant execute on function private.graphytion_workspace_role(uuid) to authenticated;
grant execute on function private.graphytion_workspace_owner(uuid) to authenticated;

drop policy if exists workspaces_select_member on public.workspaces;
create policy workspaces_select_member on public.workspaces for select to authenticated
using (private.graphytion_is_workspace_member(id));

drop policy if exists workspaces_update_admin on public.workspaces;
create policy workspaces_update_admin on public.workspaces for update to authenticated
using (private.graphytion_workspace_role(id) in ('owner','admin'))
with check (
  private.graphytion_workspace_role(id) in ('owner','admin')
  and owner_user_id=private.graphytion_workspace_owner(id)
);

drop policy if exists workspace_members_select_member on public.workspace_members;
create policy workspace_members_select_member on public.workspace_members for select to authenticated
using (private.graphytion_workspace_role(workspace_id) in ('owner','admin','editor','member'));

drop policy if exists video_projects_member_select on public.video_projects;
create policy video_projects_member_select on public.video_projects for select to authenticated
using (
  private.graphytion_workspace_role(workspace_id) in ('owner','admin','editor','member','viewer')
  and status <> 'deleted'
);

drop policy if exists project_settings_member_select on public.project_settings;
create policy project_settings_member_select on public.project_settings for select to authenticated
using (
  exists (
    select 1 from public.video_projects p
    where p.id=project_id
      and private.graphytion_workspace_role(p.workspace_id) in ('owner','admin','editor','member','viewer')
  )
);

drop policy if exists audit_logs_workspace_read on public.audit_logs;
create policy audit_logs_workspace_read on public.audit_logs for select to authenticated
using (
  workspace_id is not null
  and private.graphytion_workspace_role(workspace_id) in ('owner','admin')
);

drop policy if exists profiles_select_self on public.profiles;
create policy profiles_select_self on public.profiles for select to authenticated
using (id=(select auth.uid()));

drop policy if exists profiles_update_self on public.profiles;
create policy profiles_update_self on public.profiles for update to authenticated
using (id=(select auth.uid()))
with check (id=(select auth.uid()));

-- Keep the pre-existing RLS auto-enable trigger callable only by the database trigger system.
revoke execute on function public.rls_auto_enable() from public, anon, authenticated;

commit;
