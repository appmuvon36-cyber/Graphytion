-- Platform-level rendering guardrails used by FastAPI job submission and worker claims.
-- Additive singleton configuration; all changes are audited by the API.
begin;

create table if not exists public.platform_render_settings (
  singleton_id smallint primary key default 1 check (singleton_id = 1),
  max_concurrent_jobs smallint not null default 2 check (max_concurrent_jobs between 1 and 8),
  lease_seconds integer not null default 300 check (lease_seconds between 60 and 3600),
  max_attempts smallint not null default 3 check (max_attempts between 1 and 10),
  max_output_bytes bigint not null default 536870912
    check (max_output_bytes between 1048576 and 2147483648),
  updated_by uuid references public.profiles(id),
  updated_at timestamptz not null default now()
);

insert into public.platform_render_settings(singleton_id)
values (1)
on conflict (singleton_id) do nothing;

alter table public.platform_render_settings enable row level security;

drop policy if exists platform_render_settings_runtime_read on public.platform_render_settings;
create policy platform_render_settings_runtime_read
on public.platform_render_settings
for select to graphytion_api
using (true);

drop policy if exists platform_render_settings_admin_update on public.platform_render_settings;
create policy platform_render_settings_admin_update
on public.platform_render_settings
for update to graphytion_api
using (private.graphytion_is_platform_admin())
with check (private.graphytion_is_platform_admin());

revoke all on public.platform_render_settings from public, anon, authenticated, service_role;
grant select, update on public.platform_render_settings to graphytion_api;

commit;
