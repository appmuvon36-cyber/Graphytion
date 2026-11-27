-- Keep queued child jobs active in their parent step and allow retry recovery.
begin;
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
      when j.status='completed' then 'completed'
      when j.status in ('failed','provider_unavailable') then 'failed'
      when j.status='cancelled' then 'cancelled'
      when j.status in ('processing','running','rendering','cancel_requested') then 'running'
      when j.status in ('queued','retry_wait','pending') then 'running'
      else s.status end,
      completed_at=case when j.status in ('completed','failed','provider_unavailable','cancelled') then coalesce(s.completed_at,now()) else null end,
      updated_at=now()
  from (
    select id,production_run_id,workspace_id,project_id,status,'agent_task'::text kind
    from public.agent_tasks where production_run_id=p_run_id
    union all
    select id,production_run_id,workspace_id,project_id,status,'media_generation'::text
    from public.media_generation_jobs where production_run_id=p_run_id
    union all
    select id,production_run_id,workspace_id,project_id,status,'audio_generation'::text
    from public.audio_generations where production_run_id=p_run_id
    union all
    select id,production_run_id,workspace_id,project_id,status,'render_job'::text
    from public.render_jobs where production_run_id=p_run_id
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
  set status='cancelled',completed_at=now(),updated_at=now(),
      error_code='DEPENDENCY_TERMINAL'
  where s.production_run_id=p_run_id and s.status in ('pending','ready','waiting_approval')
    and exists (
      select 1 from public.production_run_step_dependencies d
      join public.production_run_steps parent on parent.id=d.depends_on_step_id
      where d.step_id=s.id and parent.status='cancelled'
    );

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
        else 'ready_for_review'
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
