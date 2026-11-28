-- Workspace creation is a FastAPI-only operation executed as graphytion_runtime.
-- The runtime role needs narrowly scoped INSERT policies for the workspace and
-- its initial owner membership, plus actor-scoped idempotency storage.
-- No existing rows are modified or deleted.

begin;

grant insert on public.workspaces to graphytion_runtime;
drop policy if exists workspaces_runtime_create_owner on public.workspaces;
create policy workspaces_runtime_create_owner
  on public.workspaces
  for insert
  to graphytion_runtime
  with check (owner_user_id = auth.uid());

grant insert on public.workspace_members to graphytion_runtime;
drop policy if exists workspace_members_runtime_create_owner on public.workspace_members;
create policy workspace_members_runtime_create_owner
  on public.workspace_members
  for insert
  to graphytion_runtime
  with check (
    user_id = auth.uid()
    and role = 'owner'
    and status = 'active'
    and exists (
      select 1
      from public.workspaces w
      where w.id = workspace_id
        and w.owner_user_id = auth.uid()
    )
  );

-- reserve_idempotency() performs actor-scoped expiry cleanup, reservation,
-- replay lookup and completion in the same transaction as workspace creation.
grant select, insert, update, delete
  on public.api_idempotency_keys to graphytion_runtime;

drop policy if exists api_idempotency_runtime_select_own on public.api_idempotency_keys;
create policy api_idempotency_runtime_select_own
  on public.api_idempotency_keys
  for select
  to graphytion_runtime
  using (actor_user_id = auth.uid());

drop policy if exists api_idempotency_runtime_insert_own on public.api_idempotency_keys;
create policy api_idempotency_runtime_insert_own
  on public.api_idempotency_keys
  for insert
  to graphytion_runtime
  with check (actor_user_id = auth.uid());

drop policy if exists api_idempotency_runtime_update_own on public.api_idempotency_keys;
create policy api_idempotency_runtime_update_own
  on public.api_idempotency_keys
  for update
  to graphytion_runtime
  using (actor_user_id = auth.uid())
  with check (actor_user_id = auth.uid());

drop policy if exists api_idempotency_runtime_delete_own on public.api_idempotency_keys;
create policy api_idempotency_runtime_delete_own
  on public.api_idempotency_keys
  for delete
  to graphytion_runtime
  using (actor_user_id = auth.uid());

commit;
