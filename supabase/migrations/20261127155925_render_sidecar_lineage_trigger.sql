-- Keep Production Run aggregates fresh when preview/thumbnail sidecars are persisted.
begin;
drop trigger if exists render_artifacts_refresh_production_run on public.render_artifacts;
create trigger render_artifacts_refresh_production_run
after insert or update on public.render_artifacts
for each row execute function private.graphytion_refresh_production_run_from_child();
commit;
