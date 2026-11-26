-- Graphytion Phase 02: least-privilege FastAPI SQL role with request-scoped RLS.
-- The login role remains NOLOGIN until its password is set out-of-band by the project owner.
begin;

alter table public.profiles add column if not exists email text;
create index if not exists profiles_email_lower_idx
  on public.profiles(lower(email)) where email is not null;

create or replace function public.graphytion_sync_auth_profile()
returns trigger
language plpgsql
security definer
set search_path = public, auth
as $profile_sync$
begin
  insert into public.profiles(id,email,display_name)
  values (
    new.id,
    lower(new.email),
    nullif(btrim(coalesce(new.raw_user_meta_data->>'display_name',new.raw_user_meta_data->>'full_name','')), '')
  )
  on conflict (id) do update set
    email=excluded.email,
    display_name=coalesce(public.profiles.display_name,excluded.display_name),
    updated_at=now();
  return new;
end
$profile_sync$;

drop trigger if exists graphytion_auth_user_profile on auth.users;
create trigger graphytion_auth_user_profile
after insert or update on auth.users
for each row execute function public.graphytion_sync_auth_profile();

insert into public.profiles(id,email,display_name)
select
  u.id,
  lower(u.email),
  nullif(btrim(coalesce(u.raw_user_meta_data->>'display_name',u.raw_user_meta_data->>'full_name','')), '')
from auth.users u
on conflict (id) do update set
  email=excluded.email,
  display_name=coalesce(public.profiles.display_name,excluded.display_name),
  updated_at=now();

do $runtime_roles$
begin
  if not exists (select 1 from pg_roles where rolname='graphytion_runtime') then
    execute 'create role graphytion_runtime nologin inherit';
  end if;
  if not exists (select 1 from pg_roles where rolname='graphytion_api') then
    execute 'create role graphytion_api nologin inherit';
  end if;
end
$runtime_roles$;

grant authenticated to graphytion_runtime;
grant graphytion_runtime to graphytion_api;
grant usage on schema public, private, auth to graphytion_runtime;
grant execute on function auth.uid() to graphytion_runtime;
-- Grant only the SQL operations and columns used by FastAPI.
-- No runtime DELETE on memberships, invitations, projects, project settings or audit history.
grant select on table public.workspaces to graphytion_runtime;
grant insert (name,slug,owner_user_id) on table public.workspaces to graphytion_runtime;
grant update (name,settings,updated_at) on table public.workspaces to graphytion_runtime;
grant delete on table public.workspaces to graphytion_runtime;

grant select on table public.workspace_members to graphytion_runtime;
grant insert (workspace_id,user_id,role,status)
  on table public.workspace_members to graphytion_runtime;
grant update (role,status) on table public.workspace_members to graphytion_runtime;

grant select on table public.workspace_invitations to graphytion_runtime;
grant insert (workspace_id,email,role,token_hash,invited_by,expires_at,
              delivery_status,delivery_attempts,last_delivery_attempt_at)
  on table public.workspace_invitations to graphytion_runtime;
grant update (token_hash,expires_at,accepted_at,cancelled_at,delivery_status,
              delivery_attempts,last_delivery_attempt_at,last_delivery_error,
              provider_message_id,sent_at)
  on table public.workspace_invitations to graphytion_runtime;

grant select on table public.video_projects to graphytion_runtime;
grant insert (workspace_id,created_by,name,description,production_mode,
              default_language,target_duration_ms,aspect_ratio,width,height,fps)
  on table public.video_projects to graphytion_runtime;
grant update (name,description,production_mode,default_language,target_duration_ms,
              aspect_ratio,width,height,fps,status,updated_at)
  on table public.video_projects to graphytion_runtime;

grant select on table public.project_settings to graphytion_runtime;
grant insert (project_id,settings) on table public.project_settings to graphytion_runtime;
grant update (settings,version,updated_at) on table public.project_settings to graphytion_runtime;

grant select,delete on table public.api_idempotency_keys to graphytion_runtime;
grant insert (actor_user_id,operation,idempotency_key,request_hash)
  on table public.api_idempotency_keys to graphytion_runtime;
grant update (response_body,completed_at) on table public.api_idempotency_keys to graphytion_runtime;

grant select,insert on table public.audit_logs to graphytion_runtime;

-- The service-role key is used only by the private Storage adapter, never by the
-- FastAPI SQL path or browser Data API. Remove its broad legacy grants on domain tables.
revoke all privileges on table
  public.profiles, public.workspaces, public.workspace_members,
  public.workspace_invitations, public.video_projects, public.project_settings,
  public.api_idempotency_keys, public.audit_logs
from service_role;
grant execute on function private.graphytion_is_workspace_member(uuid) to graphytion_runtime;
grant execute on function private.graphytion_workspace_role(uuid) to graphytion_runtime;
grant execute on function private.graphytion_workspace_owner(uuid) to graphytion_runtime;

-- Email and immutable profile identity are trigger-managed; runtime receives only required profile columns.
revoke select,insert,update,delete on table public.profiles
  from authenticated,graphytion_runtime;
grant select (id,display_name,avatar_path,bio,locale,timezone,created_at,updated_at)
  on table public.profiles to authenticated,graphytion_runtime;
grant insert (id)
  on table public.profiles to graphytion_runtime;
grant update (display_name,bio,locale,timezone,avatar_path,updated_at)
  on table public.profiles to graphytion_runtime;
grant update (display_name,bio,locale,timezone)
  on table public.profiles to authenticated;

create or replace function private.graphytion_is_workspace_owner(target_workspace uuid)
returns boolean
language sql stable security definer
set search_path = public, auth
as $is_owner$
  select exists (
    select 1 from public.workspaces w
    where w.id=target_workspace and w.owner_user_id=auth.uid()
  )
$is_owner$;

create or replace function private.graphytion_workspace_has_active_member_email(
  target_workspace uuid, target_email text
)
returns boolean
language sql stable security definer
set search_path = public, auth
as $member_email$
  select exists (
    select 1
    from public.profiles p
    join public.workspace_members m on m.user_id=p.id
    where m.workspace_id=target_workspace
      and lower(p.email)=lower(target_email)
      and m.status='active'
  )
$member_email$;

create or replace function private.graphytion_invitation_matches_user(
  target_email text, target_user uuid
)
returns boolean
language sql stable security definer
set search_path = public, auth
as $invitee_email$
  select target_user=auth.uid() and exists (
    select 1 from public.profiles p
    where p.id=target_user and lower(p.email)=lower(target_email)
  )
$invitee_email$;

create or replace function private.graphytion_can_accept_invitation(
  target_workspace uuid, target_role text
)
returns boolean
language sql stable security definer
set search_path = public, auth
as $can_accept$
  select exists (
    select 1
    from public.workspace_invitations i
    join public.profiles p on lower(p.email)=lower(i.email)
    join public.workspace_members inviter
      on inviter.workspace_id=i.workspace_id and inviter.user_id=i.invited_by
    where i.workspace_id=target_workspace
      and i.role=target_role
      and p.id=auth.uid()
      and i.accepted_at is null
      and i.cancelled_at is null
      and i.expires_at>now()
      and inviter.status='active'
      and inviter.role in ('owner','admin')
      and (i.role<>'admin' or inviter.role='owner')
  )
$can_accept$;

revoke all on function private.graphytion_is_workspace_owner(uuid) from public,anon,authenticated;
revoke all on function private.graphytion_workspace_has_active_member_email(uuid,text) from public,anon,authenticated;
revoke all on function private.graphytion_invitation_matches_user(text,uuid) from public,anon,authenticated;
revoke all on function private.graphytion_can_accept_invitation(uuid,text) from public,anon,authenticated;
grant execute on function private.graphytion_is_workspace_owner(uuid) to graphytion_runtime;
grant execute on function private.graphytion_workspace_has_active_member_email(uuid,text) to graphytion_runtime;
grant execute on function private.graphytion_invitation_matches_user(text,uuid) to graphytion_runtime;
grant execute on function private.graphytion_can_accept_invitation(uuid,text) to graphytion_runtime;

create or replace function private.graphytion_is_resend_webhook()
returns boolean
language sql stable
set search_path = public
as $resend_context$
  select coalesce(current_setting('app.graphytion.internal',true),'')='resend_webhook'
$resend_context$;
revoke all on function private.graphytion_is_resend_webhook() from public,anon,authenticated;
grant execute on function private.graphytion_is_resend_webhook() to graphytion_runtime;

drop policy if exists profiles_select_workspace_members on public.profiles;
create policy profiles_select_workspace_members
on public.profiles for select to graphytion_runtime
using (
  exists (
    select 1
    from public.workspace_members mine
    join public.workspace_members peer on peer.workspace_id=mine.workspace_id
    where mine.user_id=auth.uid() and mine.status='active'
      and peer.user_id=profiles.id and peer.status='active'
  )
);

drop policy if exists profiles_insert_self_runtime on public.profiles;
create policy profiles_insert_self_runtime
on public.profiles for insert to graphytion_runtime
with check (id=auth.uid());

drop policy if exists workspaces_insert_owner_runtime on public.workspaces;
create policy workspaces_insert_owner_runtime
on public.workspaces for insert to graphytion_runtime
with check (owner_user_id=auth.uid());

drop policy if exists workspaces_delete_owner_runtime on public.workspaces;
create policy workspaces_delete_owner_runtime
on public.workspaces for delete to graphytion_runtime
using (private.graphytion_workspace_role(id)='owner');

drop policy if exists workspace_members_insert_runtime on public.workspace_members;
create policy workspace_members_insert_runtime
on public.workspace_members for insert to graphytion_runtime
with check (
  (user_id=auth.uid() and role='owner'
    and private.graphytion_is_workspace_owner(workspace_id))
  or private.graphytion_can_accept_invitation(workspace_id,role)
);

drop policy if exists workspace_members_update_runtime on public.workspace_members;
create policy workspace_members_update_runtime
on public.workspace_members for update to graphytion_runtime
using (
  private.graphytion_workspace_role(workspace_id) in ('owner','admin')
  or user_id=auth.uid()
)
with check (
  (
    private.graphytion_workspace_role(workspace_id) in ('owner','admin')
    and role<>'owner'
    and (role<>'admin' or private.graphytion_workspace_role(workspace_id)='owner')
  )
  or (user_id=auth.uid() and status='left')
  or (
    user_id=auth.uid()
    and status='active'
    and private.graphytion_can_accept_invitation(workspace_id,role)
  )
);

drop policy if exists workspace_invitations_select_runtime on public.workspace_invitations;
create policy workspace_invitations_select_runtime
on public.workspace_invitations for select to graphytion_runtime
using (
  private.graphytion_workspace_role(workspace_id) in ('owner','admin')
  or private.graphytion_is_resend_webhook()
  or (
    private.graphytion_invitation_matches_user(email,auth.uid())
    and accepted_at is null and cancelled_at is null and expires_at>now()
  )
);

drop policy if exists workspace_invitations_insert_runtime on public.workspace_invitations;
create policy workspace_invitations_insert_runtime
on public.workspace_invitations for insert to graphytion_runtime
with check (
  invited_by=auth.uid()
  and private.graphytion_workspace_role(workspace_id) in ('owner','admin')
  and (role<>'admin' or private.graphytion_workspace_role(workspace_id)='owner')
);

drop policy if exists workspace_invitations_update_runtime on public.workspace_invitations;
create policy workspace_invitations_update_runtime
on public.workspace_invitations for update to graphytion_runtime
using (
  private.graphytion_workspace_role(workspace_id) in ('owner','admin')
  or (
    private.graphytion_invitation_matches_user(email,auth.uid())
    and accepted_at is null and cancelled_at is null and expires_at>now()
  )
)
with check (
  private.graphytion_workspace_role(workspace_id) in ('owner','admin')
  or private.graphytion_is_resend_webhook()
  or (
    private.graphytion_invitation_matches_user(email,auth.uid())
    and accepted_at is not null and cancelled_at is null
  )
);

drop policy if exists video_projects_insert_runtime on public.video_projects;
create policy video_projects_insert_runtime
on public.video_projects for insert to graphytion_runtime
with check (
  created_by=auth.uid()
  and private.graphytion_workspace_role(workspace_id) in ('owner','admin','editor','member')
);

drop policy if exists video_projects_update_runtime on public.video_projects;
create policy video_projects_update_runtime
on public.video_projects for update to graphytion_runtime
using (
  private.graphytion_workspace_role(workspace_id) in ('owner','admin','editor','member')
)
with check (
  private.graphytion_workspace_role(workspace_id) in ('owner','admin')
  or (
    status <> 'deleted'
    and private.graphytion_workspace_role(workspace_id) in ('editor','member')
  )
);

drop policy if exists project_settings_insert_runtime on public.project_settings;
create policy project_settings_insert_runtime
on public.project_settings for insert to graphytion_runtime
with check (
  exists (
    select 1 from public.video_projects p
    where p.id=project_id
      and private.graphytion_workspace_role(p.workspace_id) in ('owner','admin','editor','member')
  )
);

drop policy if exists project_settings_update_runtime on public.project_settings;
create policy project_settings_update_runtime
on public.project_settings for update to graphytion_runtime
using (
  exists (
    select 1 from public.video_projects p
    where p.id=project_id
      and private.graphytion_workspace_role(p.workspace_id) in ('owner','admin','editor','member')
  )
)
with check (
  exists (
    select 1 from public.video_projects p
    where p.id=project_id
      and private.graphytion_workspace_role(p.workspace_id) in ('owner','admin','editor','member')
  )
);

create or replace function public.graphytion_protect_invitation_update()
returns trigger
language plpgsql
set search_path = public, private, auth
as $invitation_guard$
declare
  actor_role text;
begin
  actor_role := private.graphytion_workspace_role(old.workspace_id);
  if new.id is distinct from old.id
    or new.workspace_id is distinct from old.workspace_id
    or new.email is distinct from old.email
    or new.role is distinct from old.role
    or new.invited_by is distinct from old.invited_by
    or new.created_at is distinct from old.created_at
  then
    raise exception 'invitation identity and role are immutable'
      using errcode = '42501';
  end if;

  if private.graphytion_is_resend_webhook() then
    if new.email is distinct from old.email
      or new.role is distinct from old.role
      or new.token_hash is distinct from old.token_hash
      or new.expires_at is distinct from old.expires_at
      or new.accepted_at is distinct from old.accepted_at
      or new.cancelled_at is distinct from old.cancelled_at
      or new.delivery_attempts is distinct from old.delivery_attempts
      or new.provider_message_id is distinct from old.provider_message_id
      or new.sent_at is distinct from old.sent_at
      or new.last_delivery_attempt_at is distinct from old.last_delivery_attempt_at
    then
      raise exception 'provider webhook may only update delivery state'
        using errcode = '42501';
    end if;
    return new;
  end if;

  if actor_role in ('owner','admin') then
    if old.role='admin' and actor_role<>'owner' then
      raise exception 'only workspace owner can manage administrator invitations'
        using errcode = '42501';
    end if;
  else
    if not private.graphytion_invitation_matches_user(old.email,auth.uid())
      or old.accepted_at is not null
      or new.accepted_at is null
      or new.cancelled_at is distinct from old.cancelled_at
      or new.token_hash is distinct from old.token_hash
      or new.expires_at is distinct from old.expires_at
      or new.delivery_status is distinct from old.delivery_status
      or new.delivery_attempts is distinct from old.delivery_attempts
      or new.provider_message_id is distinct from old.provider_message_id
      or new.sent_at is distinct from old.sent_at
      or new.last_delivery_attempt_at is distinct from old.last_delivery_attempt_at
      or new.last_delivery_error is distinct from old.last_delivery_error
    then
      raise exception 'invitee may only accept their own pending invitation'
        using errcode = '42501';
    end if;
  end if;
  return new;
end
$invitation_guard$;

revoke all on function public.graphytion_protect_invitation_update() from public,anon,authenticated,graphytion_runtime;
drop trigger if exists workspace_invitations_protect_update on public.workspace_invitations;
create trigger workspace_invitations_protect_update
before update on public.workspace_invitations
for each row execute function public.graphytion_protect_invitation_update();

drop policy if exists api_idempotency_runtime_all on public.api_idempotency_keys;
create policy api_idempotency_runtime_all
on public.api_idempotency_keys for all to graphytion_runtime
using (actor_user_id=auth.uid())
with check (actor_user_id=auth.uid());

drop policy if exists audit_logs_runtime_insert on public.audit_logs;
create policy audit_logs_runtime_insert
on public.audit_logs for insert to graphytion_runtime
with check (
  (actor_user_id=auth.uid() and (workspace_id is null or private.graphytion_is_workspace_member(workspace_id)))
  or (actor_user_id is null and workspace_id is null)
  or (
    actor_user_id is null
    and workspace_id is not null
    and action in (
      'workspace.invitation.email_sent',
      'workspace.invitation.email_delivered',
      'workspace.invitation.email_delivery_delayed',
      'workspace.invitation.email_bounced',
      'workspace.invitation.email_complained',
      'workspace.invitation.email_failed'
    )
    and private.graphytion_is_resend_webhook()
  )
);

-- Keep the API login role non-administrative and unable to create schema objects.
alter role graphytion_runtime nologin nosuperuser nocreatedb nocreaterole nobypassrls inherit noreplication;
alter role graphytion_api nologin nosuperuser nocreatedb nocreaterole nobypassrls inherit noreplication;
revoke create on schema public,private from graphytion_runtime,graphytion_api;
comment on role graphytion_runtime is 'Non-login RLS-scoped privilege group for Graphytion FastAPI.';
comment on role graphytion_api is 'Non-login runtime database identity; owner must set LOGIN and password out-of-band.';

commit;

-- Owner action after this migration:
-- Set a strong unique password and LOGIN for graphytion_api in the Supabase SQL editor/secret manager.
-- Then set DATABASE_URL username=graphytion_api, using the password only in the server secret store.
