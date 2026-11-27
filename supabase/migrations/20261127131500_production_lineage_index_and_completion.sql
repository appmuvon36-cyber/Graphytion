-- Complete production state aggregation and add exact FK-leading indexes.
-- Safe/additive: no rows or existing objects are removed.
begin;
create index if not exists agent_tasks_parent_step_scope_idx on public.agent_tasks(parent_step_id,production_run_id,workspace_id,project_id);
create index if not exists agent_tasks_run_scope_idx on public.agent_tasks(production_run_id,workspace_id,project_id);
create index if not exists audio_generations_parent_step_scope_idx on public.audio_generations(parent_step_id,production_run_id,workspace_id,project_id);
create index if not exists audio_generations_run_scope_idx on public.audio_generations(production_run_id,workspace_id,project_id);
create index if not exists conversation_messages_owner_idx on public.conversation_messages(owner_user_id);
create index if not exists conversation_messages_workspace_idx on public.conversation_messages(workspace_id);
create index if not exists conversation_threads_owner_idx on public.conversation_threads(owner_user_id);
create index if not exists conversation_threads_project_workspace_idx on public.conversation_threads(project_id,workspace_id);
create index if not exists media_generation_jobs_parent_step_scope_idx on public.media_generation_jobs(parent_step_id,production_run_id,workspace_id,project_id);
create index if not exists media_generation_jobs_run_scope_idx on public.media_generation_jobs(production_run_id,workspace_id,project_id);
create index if not exists memory_items_project_workspace_idx on public.memory_items(project_id,workspace_id);
create index if not exists production_run_step_assets_asset_scope_idx on public.production_run_step_assets(asset_id,workspace_id,project_id);
create index if not exists production_run_step_assets_created_by_idx on public.production_run_step_assets(created_by);
create index if not exists production_run_step_assets_step_scope_idx on public.production_run_step_assets(step_id,production_run_id,workspace_id,project_id);
create index if not exists production_run_step_dependencies_parent_scope_idx on public.production_run_step_dependencies(depends_on_step_id,production_run_id,workspace_id,project_id);
create index if not exists production_run_step_dependencies_step_scope_idx on public.production_run_step_dependencies(step_id,production_run_id,workspace_id,project_id);
create index if not exists production_run_steps_approved_by_idx on public.production_run_steps(approved_by);
create index if not exists production_run_steps_run_scope_idx on public.production_run_steps(production_run_id,workspace_id,project_id);
create index if not exists project_assets_parent_step_scope_idx on public.project_assets(parent_step_id,production_run_id,workspace_id,project_id);
create index if not exists project_assets_run_scope_idx on public.project_assets(production_run_id,workspace_id,project_id);
create index if not exists render_artifacts_parent_step_scope_idx on public.render_artifacts(parent_step_id,production_run_id,workspace_id,project_id);
create index if not exists render_artifacts_run_scope_idx on public.render_artifacts(production_run_id,workspace_id,project_id);
create index if not exists render_jobs_parent_step_scope_idx on public.render_jobs(parent_step_id,production_run_id,workspace_id,project_id);
create index if not exists render_jobs_run_scope_idx on public.render_jobs(production_run_id,workspace_id,project_id);
create index if not exists subtitle_tracks_parent_step_scope_idx on public.subtitle_tracks(parent_step_id,production_run_id,workspace_id,project_id);
create index if not exists subtitle_tracks_run_scope_idx on public.subtitle_tracks(production_run_id,workspace_id,project_id);
create index if not exists video_timelines_parent_step_scope_idx on public.video_timelines(parent_step_id,production_run_id,workspace_id,project_id);
create index if not exists video_timelines_run_scope_idx on public.video_timelines(production_run_id,workspace_id,project_id);
create or replace function private.graphytion_sync_production_run(p_run_id uuid)
returns jsonb
language plpgsql
security invoker
set search_path = public, private, pg_temp
as $$
declare
  v_workspace uuid;
  v_project uuid;
  v_total integer;
  v_completed integer;
  v_failed integer;
  v_cancelled integer;
  v_waiting integer;
  v_active integer;
  v_ready integer;
  v_progress numeric;
  v_status text;
  v_stage text;
begin
  select workspace_id,project_id into v_workspace,v_project
  from public.production_runs where id=p_run_id for update;
  if not found then return jsonb_build_object('found',false); end if;

  -- Mirror asynchronous child job state into its owning step. This never
  -- re-enqueues a child job and therefore cannot duplicate provider operations.
  update public.production_run_steps s
  set status=case
      when j.status in ('completed','succeeded') then 'completed'
      when j.status in ('failed','provider_unavailable') then 'failed'
      when j.status='cancelled' then 'cancelled'
      when j.status in ('processing','running','rendering','cancel_requested','queued','retry_wait','pending') then 'running'
      else s.status end,
      output_refs=case when j.status='completed' then j.output_refs else s.output_refs end,
      completed_at=case when j.status in ('completed','failed','provider_unavailable','cancelled') then coalesce(s.completed_at,now()) else null end,
      updated_at=now()
  from (
    select id,production_run_id,workspace_id,project_id,status,'agent_task'::text kind,
      jsonb_build_object('output_artifact_id',output_artifact_id) output_refs
    from public.agent_tasks where production_run_id=p_run_id
    union all
    select id,production_run_id,workspace_id,project_id,status,'media_generation'::text,
      jsonb_build_object('asset_id',asset_id,'mime_type',output_mime_type,'size_bytes',output_size_bytes,'sha256',output_sha256,'provider_operation_id',provider_job_id)
    from public.media_generation_jobs where production_run_id=p_run_id
    union all
    select id,production_run_id,workspace_id,project_id,status,'audio_generation'::text,
      jsonb_build_object('asset_id',asset_id,'alignment_status',alignment_status)
    from public.audio_generations where production_run_id=p_run_id
    union all
    select r.id,r.production_run_id,r.workspace_id,r.project_id,r.status,'render_job'::text,
      jsonb_build_object('render_job_id',r.id,'asset_id',(select a.id from public.project_assets a where a.workspace_id=r.workspace_id and a.project_id=r.project_id and a.object_path=r.output_path limit 1),'bucket',r.output_bucket,'object_path',r.output_path,'size_bytes',r.output_size_bytes,'sha256',r.output_sha256,'timeline_hash',r.timeline_hash,'composition_version',r.composition_version)
    from public.render_jobs r where r.production_run_id=p_run_id
  ) j
  where s.production_run_id=p_run_id and s.child_job_id=j.id
    and s.child_job_type=j.kind and s.workspace_id=j.workspace_id and s.project_id=j.project_id
    and s.status not in ('completed','cancelled');

  -- A dependency is ready only after every prerequisite is completed.
  update public.production_run_steps s
  set status=case when s.requires_approval and s.approved_at is null
                  then 'waiting_approval' else 'ready' end,
      updated_at=now()
  where s.production_run_id=p_run_id and s.status='pending'
    and not exists (
      select 1 from public.production_run_step_dependencies d
      join public.production_run_steps parent on parent.id=d.depends_on_step_id
      where d.step_id=s.id and parent.status<>'completed'
    )
    and not exists (
      select 1 from public.production_run_step_dependencies d
      join public.production_run_steps parent on parent.id=d.depends_on_step_id
      where d.step_id=s.id and parent.status='cancelled'
    );

  -- Failure/cancellation propagates only to steps that have not started.
  update public.production_run_steps s
  set status=case when exists (
        select 1 from public.production_run_step_dependencies d
        join public.production_run_steps parent on parent.id=d.depends_on_step_id
        where d.step_id=s.id and parent.status='failed'
      ) then 'failed' else 'cancelled' end,
      completed_at=now(),updated_at=now(),
      error_code=case when exists (
        select 1 from public.production_run_step_dependencies d
        join public.production_run_steps parent on parent.id=d.depends_on_step_id
        where d.step_id=s.id and parent.status='failed'
      ) then 'DEPENDENCY_FAILED' else 'DEPENDENCY_CANCELLED' end
  where s.production_run_id=p_run_id and s.status in ('pending','ready','waiting_approval')
    and exists (
      select 1 from public.production_run_step_dependencies d
      join public.production_run_steps parent on parent.id=d.depends_on_step_id
      where d.step_id=s.id and parent.status in ('failed','cancelled')
    );

  -- A media output is persisted by the worker before this step is completed.
  -- Promote the explicit asset-persistence node only when its referenced asset
  -- exists, is active, and belongs to the same project/workspace/run.
  update public.production_run_steps asset_step
  set status='completed',
      output_refs=media.output_refs,
      completed_at=now(),updated_at=now()
  from public.production_run_step_dependencies d
  join public.production_run_steps media on media.id=d.depends_on_step_id
  join public.project_assets asset
    on asset.id=nullif(media.output_refs->>'asset_id','')::uuid
   and asset.workspace_id=media.workspace_id and asset.project_id=media.project_id
   and asset.status='active' and asset.deleted_at is null
  where d.step_id=asset_step.id and asset_step.production_run_id=p_run_id
    and asset_step.step_type='asset_persistence'
    and asset_step.status in ('ready','running')
    and media.step_type in ('media_generation','voiceover')
    and media.status='completed';

  -- Timeline persistence is the immutable composition snapshot boundary.
  update public.production_run_steps composition_step
  set status='completed',output_refs=timeline.output_refs,
      completed_at=now(),updated_at=now()
  from public.production_run_step_dependencies d
  join public.production_run_steps timeline on timeline.id=d.depends_on_step_id
  where d.step_id=composition_step.id and composition_step.production_run_id=p_run_id
    and composition_step.step_type='composition'
    and composition_step.status in ('ready','running')
    and timeline.step_type='timeline' and timeline.status='completed';

  -- Quality and delivery steps are completed only after the render worker
  -- persisted a final private object and its matching Asset Library record.
  update public.production_run_steps qc
  set status='completed',
      output_refs=jsonb_build_object(
        'render_job_id',r.id,'asset_id',a.id,'bucket',r.output_bucket,
        'object_path',r.output_path,'mime_type',a.content_type,
        'size_bytes',r.output_size_bytes,'sha256',r.output_sha256,
        'timeline_hash',r.timeline_hash,'composition_version',r.composition_version
      ),
      completed_at=now(),updated_at=now()
  from public.production_run_step_dependencies d
  join public.production_run_steps render_step on render_step.id=d.depends_on_step_id
  join public.render_jobs r on r.id=render_step.child_job_id
  join public.project_assets a on a.object_path=r.output_path
    and a.bucket=r.output_bucket and a.workspace_id=r.workspace_id
    and a.project_id=r.project_id and a.status='active' and a.deleted_at is null
    and a.sha256=r.output_sha256 and a.size_bytes=r.output_size_bytes
  where d.step_id=qc.id and qc.production_run_id=p_run_id
    and qc.step_type='quality_check' and qc.status in ('ready','running')
    and render_step.step_type='render' and render_step.status='completed'
    and r.status='completed' and r.output_bucket='render-artifacts'
    and r.output_path is not null and r.output_sha256 is not null
    and a.content_type in ('video/mp4','video/webm');

  update public.production_run_steps delivery
  set status='completed',
      output_refs=qc.output_refs || jsonb_build_object('delivery_status','available','download_endpoint','/api/v1/renders/'||(qc.output_refs->>'render_job_id')||'/download'),
      completed_at=now(),updated_at=now()
  from public.production_run_step_dependencies d
  join public.production_run_steps qc on qc.id=d.depends_on_step_id
  where d.step_id=delivery.id and delivery.production_run_id=p_run_id
    and delivery.step_type='delivery' and delivery.status in ('ready','running')
    and qc.step_type='quality_check' and qc.status='completed';

  select count(*),
    count(*) filter(where status='completed'),
    count(*) filter(where status='failed'),
    count(*) filter(where status='cancelled'),
    count(*) filter(where status='waiting_approval'),
    count(*) filter(where status='running'),
    count(*) filter(where status='ready'),
    (array_agg(step_key order by case status when 'running' then 0 when 'ready' then 1 when 'waiting_approval' then 2 else 3 end,created_at))[1]
  into v_total,v_completed,v_failed,v_cancelled,v_waiting,v_active,v_ready,v_stage
  from public.production_run_steps where production_run_id=p_run_id;

  if v_total=0 then
    return jsonb_build_object('found',true,'total',0,'status','unconfigured');
  end if;

  v_progress=round((v_completed::numeric/nullif(v_total,0))*100,2);
  if v_failed>0 then v_status='failed';
  elsif v_cancelled=v_total then v_status='cancelled';
  elsif v_completed=v_total then v_status='completed';
  elsif v_waiting>0 and v_active=0 and v_ready=0 then v_status='ready_for_review';
  elsif v_active>0 then v_status='planning';
  else v_status='queued';
  end if;

  update public.production_runs
  set progress_percent=v_progress,current_stage=v_stage,
      status=case
        when status='cancel_requested' then status
        when v_status in ('failed','cancelled','completed') then v_status
        when v_waiting>0 and v_ready=0 and v_active=0 then 'ready_for_review'
        when v_active>0 then 'planning'
        else 'queued'
      end,
      completed_at=case when v_status in ('failed','cancelled','completed') then coalesce(completed_at,now()) else completed_at end,
      updated_at=now()
  where id=p_run_id;

  return jsonb_build_object('found',true,'total',v_total,'completed',v_completed,
    'failed',v_failed,'cancelled',v_cancelled,'waiting_approval',v_waiting,
    'running',v_active,'ready',v_ready,'progress_percent',v_progress,'status',v_status);
end;
$$;
commit;
