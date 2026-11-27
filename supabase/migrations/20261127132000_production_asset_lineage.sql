-- Explicitly bind reused project assets to the step that consumes them and persist child outputs.
begin;
create unique index if not exists project_assets_id_workspace_project_uidx
  on public.project_assets(id,workspace_id,project_id);

create table if not exists public.production_run_step_assets (
  id uuid primary key default gen_random_uuid(),
  production_run_id uuid not null,
  workspace_id uuid not null,
  project_id uuid not null,
  step_id uuid not null,
  asset_id uuid not null,
  usage_role text not null default 'input' check (usage_role in ('input','reference','source','preview')),
  created_by uuid not null references public.profiles(id) on delete restrict,
  created_at timestamptz not null default now(),
  constraint production_run_step_assets_step_fk
    foreign key (step_id,production_run_id,workspace_id,project_id)
    references public.production_run_steps(id,production_run_id,workspace_id,project_id) on delete cascade,
  constraint production_run_step_assets_asset_fk
    foreign key (asset_id,workspace_id,project_id)
    references public.project_assets(id,workspace_id,project_id) on delete cascade,
  constraint production_run_step_assets_unique unique(step_id,asset_id,usage_role)
);
create index if not exists production_run_step_assets_run_idx
  on public.production_run_step_assets(production_run_id,step_id);
alter table public.production_run_step_assets enable row level security;
drop policy if exists production_run_step_assets_workspace_access on public.production_run_step_assets;
create policy production_run_step_assets_workspace_access on public.production_run_step_assets
for all to graphytion_api,graphytion_runtime
using (private.graphytion_is_workspace_member(workspace_id))
with check (private.graphytion_is_workspace_member(workspace_id));
grant select,insert,update,delete on public.production_run_step_assets to graphytion_api,graphytion_runtime;

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
  set status='cancelled',completed_at=now(),updated_at=now(),
      error_code='DEPENDENCY_TERMINAL'
  where s.production_run_id=p_run_id and s.status in ('pending','ready','waiting_approval')
    and exists (
      select 1 from public.production_run_step_dependencies d
      join public.production_run_steps parent on parent.id=d.depends_on_step_id
      where d.step_id=s.id and parent.status in ('failed','cancelled')
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
