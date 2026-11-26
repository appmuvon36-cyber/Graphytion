-- Graphytion Phase 02: remove Supabase default broad table grants and restore least privilege.
begin;

revoke all privileges on table
  public.profiles,
  public.workspaces,
  public.workspace_members,
  public.workspace_invitations,
  public.video_projects,
  public.project_settings,
  public.api_idempotency_keys,
  public.audit_logs
from anon, authenticated;

-- Authenticated Data API access is read-mostly and remains constrained by RLS.
grant select on table
  public.profiles,
  public.workspaces,
  public.workspace_members,
  public.video_projects,
  public.project_settings,
  public.audit_logs
to authenticated;

-- Only editable workspace fields are exposed; ownership, plan and identifiers stay server-managed.
grant update (name, settings) on table public.workspaces to authenticated;
grant update (display_name, bio, locale, timezone) on table public.profiles to authenticated;

-- FastAPI connects with the server-only service role and owns all mutations.
grant all privileges on table
  public.profiles,
  public.workspaces,
  public.workspace_members,
  public.workspace_invitations,
  public.video_projects,
  public.project_settings,
  public.api_idempotency_keys,
  public.audit_logs
to service_role;

commit;
