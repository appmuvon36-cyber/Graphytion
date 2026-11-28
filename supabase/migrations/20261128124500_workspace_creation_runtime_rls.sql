-- Restore the missing table privileges for the existing, narrowly scoped
-- graphytion_runtime RLS policies used by FastAPI workspace creation.
-- The RLS policies already exist; this migration does not broaden them.

begin;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname='public' and tablename='workspaces'
      and policyname='workspaces_insert_owner_runtime'
      and 'graphytion_runtime'=any(roles) and cmd='INSERT'
  ) then
    raise exception 'Required owner-scoped workspace INSERT policy is missing';
  end if;

  if not exists (
    select 1 from pg_policies
    where schemaname='public' and tablename='workspace_members'
      and policyname='workspace_members_insert_runtime'
      and 'graphytion_runtime'=any(roles) and cmd='INSERT'
  ) then
    raise exception 'Required owner-scoped membership INSERT policy is missing';
  end if;

  if not exists (
    select 1 from pg_policies
    where schemaname='public' and tablename='api_idempotency_keys'
      and policyname='api_idempotency_runtime_all'
      and 'graphytion_runtime'=any(roles) and cmd='ALL'
  ) then
    raise exception 'Required actor-scoped idempotency RLS policy is missing';
  end if;
end
$$;

grant insert on public.workspaces to graphytion_runtime;
grant insert on public.workspace_members to graphytion_runtime;
grant select, insert, update, delete
  on public.api_idempotency_keys to graphytion_runtime;

commit;
