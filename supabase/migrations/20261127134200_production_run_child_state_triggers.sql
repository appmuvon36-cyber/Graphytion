-- Refresh persisted Production Run state whenever a linked child or artifact changes.
-- Triggers use the existing PostgreSQL state machine; they do not enqueue or replay jobs.
begin;
create or replace function private.graphytion_refresh_production_run_from_child()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog, public, private
as $$
begin
  if new.production_run_id is not null then
    perform private.graphytion_sync_production_run(new.production_run_id);
  end if;
  if tg_op='UPDATE'
     and old.production_run_id is not null
     and old.production_run_id is distinct from new.production_run_id then
    perform private.graphytion_sync_production_run(old.production_run_id);
  end if;
  return new;
end;
$$;
revoke all on function private.graphytion_refresh_production_run_from_child() from public, anon, authenticated;
drop trigger if exists agent_tasks_refresh_production_run on public.agent_tasks;
create trigger agent_tasks_refresh_production_run
after insert or update on public.agent_tasks
for each row execute function private.graphytion_refresh_production_run_from_child();
drop trigger if exists media_generation_jobs_refresh_production_run on public.media_generation_jobs;
create trigger media_generation_jobs_refresh_production_run
after insert or update on public.media_generation_jobs
for each row execute function private.graphytion_refresh_production_run_from_child();
drop trigger if exists audio_generations_refresh_production_run on public.audio_generations;
create trigger audio_generations_refresh_production_run
after insert or update on public.audio_generations
for each row execute function private.graphytion_refresh_production_run_from_child();
drop trigger if exists render_jobs_refresh_production_run on public.render_jobs;
create trigger render_jobs_refresh_production_run
after insert or update on public.render_jobs
for each row execute function private.graphytion_refresh_production_run_from_child();
drop trigger if exists project_assets_refresh_production_run on public.project_assets;
create trigger project_assets_refresh_production_run
after insert or update on public.project_assets
for each row execute function private.graphytion_refresh_production_run_from_child();
drop trigger if exists subtitle_tracks_refresh_production_run on public.subtitle_tracks;
create trigger subtitle_tracks_refresh_production_run
after insert or update on public.subtitle_tracks
for each row execute function private.graphytion_refresh_production_run_from_child();
drop trigger if exists video_timelines_refresh_production_run on public.video_timelines;
create trigger video_timelines_refresh_production_run
after insert or update on public.video_timelines
for each row execute function private.graphytion_refresh_production_run_from_child();
commit;
