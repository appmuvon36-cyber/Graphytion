-- Add covering indexes for the 57 foreign keys reported by Supabase Advisor.
-- Additive only: no table, row, constraint, RLS policy, or existing index is removed.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '10min';

DO $$
DECLARE
  fk record;
  column_list text;
  suffix text;
  index_name text;
BEGIN
  FOR fk IN
    SELECT c.conrelid, c.conname, c.conkey
    FROM pg_constraint c
    JOIN pg_namespace n ON n.oid = c.connamespace
    WHERE c.contype = 'f'
      AND n.nspname = 'public'
      AND c.conname = ANY (ARRAY['agent_tasks_parent_task_id_fkey','agent_tool_audit_events_actor_user_id_fkey','agent_tool_permissions_created_by_fkey','agent_tool_permissions_updated_by_fkey','agent_tool_registry_created_by_fkey','agent_tool_registry_updated_by_fkey','ai_model_prices_created_by_fkey','ai_usage_events_agent_task_id_fkey','ai_usage_events_pricing_id_fkey','ai_usage_events_project_id_fkey','artifact_versions_created_by_fkey','artifact_versions_workspace_id_fkey','audio_analysis_artifacts_audio_asset_id_fkey','audio_analysis_artifacts_workspace_id_fkey','audio_generations_asset_id_fkey','audio_generations_requested_by_fkey','audio_generations_scene_id_fkey','brand_kits_created_by_fkey','composition_templates_created_by_fkey','creative_briefs_approved_by_fkey','creative_briefs_created_by_fkey','creative_briefs_workspace_id_fkey','motion_component_controls_updated_by_fkey','platform_admins_granted_by_fkey','platform_render_settings_updated_by_fkey','production_runs_project_id_fkey','production_runs_requested_by_fkey','quota_ledger_entries_reservation_id_fkey','quota_operation_prices_created_by_fkey','quota_reservations_project_id_fkey','render_artifacts_workspace_id_fkey','render_jobs_render_profile_id_fkey','render_jobs_requested_by_fkey','render_profiles_created_by_fkey','render_profiles_project_id_fkey','render_profiles_updated_by_fkey','render_profiles_workspace_id_fkey','storyboard_scenes_project_id_fkey','storyboard_scenes_storyboard_id_project_id_workspace_id_fkey','storyboard_scenes_workspace_id_fkey','storyboards_created_by_fkey','storyboards_script_id_project_id_workspace_id_fkey','storyboards_workspace_id_fkey','subtitle_segment_revisions_actor_user_id_fkey','subtitle_segments_audio_asset_id_fkey','subtitle_tracks_created_by_fkey','subtitle_tracks_project_id_fkey','subtitle_tracks_timeline_id_fkey','subtitle_tracks_workspace_id_fkey','video_projects_brand_kit_workspace_fk','video_scripts_brief_id_fkey','video_scripts_brief_id_project_id_workspace_id_fkey','video_scripts_created_by_fkey','video_scripts_workspace_id_fkey','video_timelines_created_by_fkey','video_timelines_workspace_id_fkey','workspace_quota_accounts_updated_by_fkey']::text[])
  LOOP
    SELECT
      string_agg(format('%I', a.attname), ', ' ORDER BY k.ordinality),
      string_agg(regexp_replace(lower(a.attname), '[^a-z0-9]+', '_', 'g'), '_' ORDER BY k.ordinality)
    INTO column_list, suffix
    FROM unnest(fk.conkey) WITH ORDINALITY AS k(attnum, ordinality)
    JOIN pg_attribute a ON a.attrelid = fk.conrelid AND a.attnum = k.attnum;

    index_name := left('fkidx_' || lower((fk.conrelid::regclass)::text) || '_' || suffix, 42)
                  || '_' || substr(md5(fk.conname), 1, 12);

    EXECUTE format(
      'CREATE INDEX IF NOT EXISTS %I ON %s (%s)',
      index_name, fk.conrelid::regclass, column_list
    );
  END LOOP;
END
$$;
