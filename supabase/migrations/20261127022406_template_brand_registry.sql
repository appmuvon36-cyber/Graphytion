-- Persistent workspace template registry and reusable brand kits.
begin;

create table if not exists public.composition_templates (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  slug text not null check (slug ~ '^[a-z0-9]+(?:-[a-z0-9]+)*$'),
  version integer not null default 1 check (version > 0),
  name text not null check (char_length(btrim(name)) between 1 and 120),
  description text,
  category text not null check (char_length(category) between 1 and 48),
  tags text[] not null default '{}',
  aspect_ratios text[] not null default array['16:9']::text[],
  composition_snapshot jsonb not null check (jsonb_typeof(composition_snapshot)='object'),
  status text not null default 'published' check (status in ('draft','published','archived')),
  created_by uuid not null references public.profiles(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(workspace_id,slug,version),
  unique(workspace_id,id),
  check (cardinality(aspect_ratios)>0 and aspect_ratios <@ array['16:9','9:16','1:1','4:5','4:3']::text[])
);
create index if not exists composition_templates_workspace_status_idx
  on public.composition_templates(workspace_id,status,category,updated_at desc);
create index if not exists composition_templates_tags_idx
  on public.composition_templates using gin(tags);

create table if not exists public.brand_kits (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  name text not null check (char_length(btrim(name)) between 1 and 120),
  version integer not null default 1 check (version > 0),
  brand_config jsonb not null check (jsonb_typeof(brand_config)='object'),
  status text not null default 'active' check (status in ('active','archived')),
  created_by uuid not null references public.profiles(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(workspace_id,name,version),
  unique(workspace_id,id)
);
create index if not exists brand_kits_workspace_status_idx
  on public.brand_kits(workspace_id,status,updated_at desc);

do $$
begin
  if not exists (select 1 from pg_constraint where conname='video_projects_brand_kit_workspace_fk') then
    alter table public.video_projects
      add constraint video_projects_brand_kit_workspace_fk
      foreign key(workspace_id,brand_kit_id)
      references public.brand_kits(workspace_id,id)
      on delete restrict;
  end if;
end $$;

create or replace function public.graphytion_touch_updated_at()
returns trigger language plpgsql set search_path=public as $$
begin new.updated_at=now(); return new; end $$;

drop trigger if exists composition_templates_touch_updated_at on public.composition_templates;
create trigger composition_templates_touch_updated_at before update on public.composition_templates
for each row execute function public.graphytion_touch_updated_at();
drop trigger if exists brand_kits_touch_updated_at on public.brand_kits;
create trigger brand_kits_touch_updated_at before update on public.brand_kits
for each row execute function public.graphytion_touch_updated_at();

alter table public.composition_templates enable row level security;
alter table public.brand_kits enable row level security;
drop policy if exists composition_templates_api_tenant on public.composition_templates;
create policy composition_templates_api_tenant on public.composition_templates
  for all to graphytion_api using (private.graphytion_is_workspace_member(workspace_id))
  with check (private.graphytion_is_workspace_member(workspace_id));
drop policy if exists brand_kits_api_tenant on public.brand_kits;
create policy brand_kits_api_tenant on public.brand_kits
  for all to graphytion_api using (private.graphytion_is_workspace_member(workspace_id))
  with check (private.graphytion_is_workspace_member(workspace_id));

revoke all on public.composition_templates,public.brand_kits from public,anon,authenticated,service_role;
grant select,insert,update,delete on public.composition_templates,public.brand_kits to graphytion_api;
grant references (workspace_id,id) on public.brand_kits to graphytion_api;

commit;
