begin;

-- The FastAPI request context explicitly SET ROLE graphytion_runtime.
-- Mirror only non-economic graphytion_api table privileges to that role.
do $$
declare
  g record;
begin
  for g in
    select distinct table_name, privilege_type
    from information_schema.role_table_grants
    where grantee = 'graphytion_api'
      and table_schema = 'public'
      and table_name not in (
        'ai_model_prices',
        'quota_ledger_entries',
        'quota_operation_prices',
        'quota_reservations',
        'workspace_quota_accounts',
        'agent_tool_audit_events',
        'audit_logs'
      )
  loop
    execute format(
      'grant %s on table public.%I to graphytion_runtime',
      g.privilege_type,
      g.table_name
    );
  end loop;
end
$$;

-- Extend the existing tenant/admin policies to the role actually assumed
-- by authenticated API requests. graphytion_api remains explicitly included.
do $$
declare
  p record;
begin
  for p in
    select schemaname, tablename, policyname
    from pg_policies
    where schemaname = 'public'
      and 'graphytion_api' = any(roles)
      and tablename not in (
        'ai_model_prices',
        'quota_ledger_entries',
        'quota_operation_prices',
        'quota_reservations',
        'workspace_quota_accounts',
        'agent_tool_audit_events',
        'audit_logs'
      )
  loop
    execute format(
      'alter policy %I on %I.%I to graphytion_api, graphytion_runtime',
      p.policyname, p.schemaname, p.tablename
    );
  end loop;
end
$$;

-- Legacy reservation release remains available only for cleanup of old jobs;
-- new personal-use generation does not reserve or debit quota.
grant select on public.quota_reservations to graphytion_runtime;
alter policy quota_reservations_member_read
  on public.quota_reservations to graphytion_api, graphytion_runtime;
alter policy quota_reservations_platform_admin_read
  on public.quota_reservations to graphytion_api, graphytion_runtime;
grant execute on function private.graphytion_release_quota(uuid, text)
  to graphytion_runtime;

-- Platform-admin checks are used by policies now shared with runtime.
grant execute on function private.graphytion_is_platform_admin()
  to graphytion_runtime;

-- Audit logs: authenticated requests may append only their own actor record
-- and only for workspaces in which they are active members.
grant select, insert on public.audit_logs to graphytion_runtime;
alter policy audit_logs_platform_admin_read
  on public.audit_logs to graphytion_api, graphytion_runtime;
drop policy if exists audit_logs_runtime_insert on public.audit_logs;
create policy audit_logs_runtime_insert
  on public.audit_logs
  for insert to graphytion_runtime
  with check (
    actor_user_id = auth.uid()
    and (workspace_id is null or private.graphytion_is_workspace_member(workspace_id))
  );

-- Agent-tool audit is workspace-only for authenticated runtime users.
-- Global/system events remain restricted to the internal API role.
grant select, insert on public.agent_tool_audit_events to graphytion_runtime;
drop policy if exists agent_tool_audit_runtime_read on public.agent_tool_audit_events;
create policy agent_tool_audit_runtime_read
  on public.agent_tool_audit_events
  for select to graphytion_runtime
  using (
    workspace_id is not null
    and private.graphytion_is_workspace_member(workspace_id)
  );
drop policy if exists agent_tool_audit_runtime_insert on public.agent_tool_audit_events;
create policy agent_tool_audit_runtime_insert
  on public.agent_tool_audit_events
  for insert to graphytion_runtime
  with check (
    workspace_id is not null
    and actor_user_id = auth.uid()
    and private.graphytion_is_workspace_member(workspace_id)
  );

commit;
