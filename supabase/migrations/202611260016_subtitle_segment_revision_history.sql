-- Subtitle segment revision history and stable segment metadata.
-- Additive only: existing segment IDs and content are preserved.
begin;

alter table public.subtitle_segments
  add column if not exists version integer not null default 1 check (version > 0),
  add column if not exists style_config jsonb not null default '{}'::jsonb,
  add column if not exists position_config jsonb not null default '{}'::jsonb,
  add column if not exists alignment_metadata jsonb not null default '{}'::jsonb,
  add column if not exists audio_asset_id uuid references public.project_assets(id) on delete set null,
  add column if not exists updated_at timestamptz not null default now();

create index if not exists subtitle_segments_track_order_idx
  on public.subtitle_segments(track_id, segment_index, id);

create table if not exists public.subtitle_segment_revisions (
  id uuid primary key default gen_random_uuid(),
  track_id uuid not null references public.subtitle_tracks(id) on delete cascade,
  segment_id uuid not null,
  revision integer not null check (revision > 0),
  operation text not null check (operation in ('created','updated','deleted','split','merged','reordered','regenerated')),
  snapshot jsonb not null,
  actor_user_id uuid references public.profiles(id) on delete set null,
  request_id text,
  created_at timestamptz not null default now(),
  unique (segment_id, revision)
);

create index if not exists subtitle_segment_revisions_track_idx
  on public.subtitle_segment_revisions(track_id, created_at desc);
create index if not exists subtitle_segment_revisions_segment_idx
  on public.subtitle_segment_revisions(segment_id, revision desc);

alter table public.subtitle_segment_revisions enable row level security;
drop policy if exists subtitle_segment_revisions_tenant_api on public.subtitle_segment_revisions;
create policy subtitle_segment_revisions_tenant_api
  on public.subtitle_segment_revisions for all to graphytion_api
  using (exists (
    select 1 from public.subtitle_tracks t
    where t.id = track_id and private.graphytion_is_workspace_member(t.workspace_id)
  ))
  with check (exists (
    select 1 from public.subtitle_tracks t
    where t.id = track_id and private.graphytion_is_workspace_member(t.workspace_id)
  ));

revoke all on public.subtitle_segment_revisions from public, anon, authenticated, service_role;
grant select, insert, update, delete on public.subtitle_segment_revisions to graphytion_api;
grant select, insert, update, delete on public.subtitle_segments to graphytion_api;

commit;
