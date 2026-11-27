-- Unified persisted production workflow graph and cross-module lineage.
-- Additive only: existing jobs/assets remain valid with nullable lineage.
begin;

create table if not exists public.production_run_steps (
  id uuid primary key default gen_random_uuid(),
  production_run_id uuid not null,
  workspace_id uuid not null,
  project_id uuid not null,
  step_key text not null check (char_length(btrim(step_key)) between 1 and 100),
  step_type text not null check (step_type in (
    'creative','agent','media_generation','asset_persistence','voiceover',
    'audio_processing','subtitle','timeline','composition','render','quality_check','delivery'
  )),
  status text not null default 'pending' check (status in (
    'pending','ready','running','waiting_approval','completed','failed','cancelled'
  )),
  input_refs jsonb not null default '{}'::jsonb,
  output_refs jsonb not null default '{}'::jsonb,
  config jsonb not null default '{}'::jsonb,
  requires_approval boolean not null default false,
  approved_by uuid references public.profiles(id) on delete set null,
  approved_at timestamptz,
  idempotency_key text not null,
  attempt_count integer not null default 0 check (attempt_count >= 0),
  max_attempts integer not null default 3 check (max_attempts between 1 and 10),
  available_at timestamptz not null default now(),
  timeout_seconds integer not null default 1800 check (timeout_seconds between 1 and 86400),
  started_at timestamptz,
  completed_at timestamptz,
  error_code text,
  error_message_safe text,
  child_job_type text check (child_job_type in ('agent_task','media_generation','audio_generation','render_job')),
  child_job_id uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint production_run_steps_run_fk
    foreign key (production_run_id,workspace_id,project_id)
    references public.production_runs(id,workspace_id,project_id) on delete cascade,
  constraint production_run_steps_id_run_scope_key
    unique (id,production_run_id,workspace_id,project_id),
  constraint production_run_steps_run_step_key
    unique (production_run_id,step_key),
  constraint production_run_steps_idempotency_key
    unique (production_run_id,idempotency_key),
  constraint production_run_steps_child_ref_check
    check ((child_job_type is null and child_job_id is null) or
           (child_job_type is not null and child_job_id is not null)),
  constraint production_run_steps_approval_check
    check ((status <> 'waiting_approval') or requires_approval)
);

create table if not exists public.production_run_step_dependencies (
  production_run_id uuid not null,
  workspace_id uuid not null,
  project_id uuid not null,
  step_id uuid not null,
  depends_on_step_id uuid not null,
  created_at timestamptz not null default now(),
  primary key (step_id,depends_on_step_id),
  constraint production_run_step_dependencies_step_fk
    foreign key (step_id,production_run_id,workspace_id,project_id)
    references public.production_run_steps(id,production_run_id,workspace_id,project_id) on delete cascade,
  constraint production_run_step_dependencies_parent_fk
    foreign key (depends_on_step_id,production_run_id,workspace_id,project_id)
    references public.production_run_steps(id,production_run_id,workspace_id,project_id) on delete cascade,
  constraint production_run_step_dependencies_no_self check (step_id <> depends_on_step_id)
);

create index if not exists production_run_steps_ready_idx
  on public.production_run_steps(available_at,created_at)
  where status='ready';
create index if not exists production_run_steps_run_status_idx
  on public.production_run_steps(production_run_id,status,created_at);
create index if not exists production_run_step_dependencies_parent_idx
  on public.production_run_step_dependencies(production_run_id,depends_on_step_id);

-- Add direct lineage columns to existing production objects.
alter table public.agent_tasks
  add column if not exists workspace_id uuid,
  add column if not exists project_id uuid,
  add column if not exists parent_step_id uuid;
update public.agent_tasks t
set workspace_id=r.workspace_id, project_id=r.project_id
from public.production_runs r
where r.id=t.production_run_id and (t.workspace_id is null or t.project_id is null);
alter table public.agent_tasks
  alter column workspace_id set not null,
  alter column project_id set not null;

alter table public.media_generation_jobs
  add column if not exists production_run_id uuid,
  add column if not exists parent_step_id uuid;
alter table public.audio_generations
  add column if not exists production_run_id uuid,
  add column if not exists parent_step_id uuid;
alter table public.render_jobs
  add column if not exists production_run_id uuid,
  add column if not exists parent_step_id uuid;
alter table public.project_assets
  add column if not exists production_run_id uuid,
  add column if not exists parent_step_id uuid;
alter table public.video_timelines
  add column if not exists production_run_id uuid,
  add column if not exists parent_step_id uuid;
alter table public.subtitle_tracks
  add column if not exists production_run_id uuid,
  add column if not exists parent_step_id uuid;
alter table public.render_artifacts
  add column if not exists production_run_id uuid,
  add column if not exists parent_step_id uuid;

-- Workspace/project-scoped composite references prevent cross-project lineage.
do $$
begin
  if not exists(select 1 from pg_constraint where conname='agent_tasks_run_scope_fk') then
    alter table public.agent_tasks add constraint agent_tasks_run_scope_fk
      foreign key (production_run_id,workspace_id,project_id)
      references public.production_runs(id,workspace_id,project_id) on delete cascade;
  end if;
  if not exists(select 1 from pg_constraint where conname='agent_tasks_parent_step_scope_fk') then
    alter table public.agent_tasks add constraint agent_tasks_parent_step_scope_fk
      foreign key (parent_step_id,production_run_id,workspace_id,project_id)
      references public.production_run_steps(id,production_run_id,workspace_id,project_id) on delete set null (parent_step_id);
  end if;
end $$;

do $$
declare t text;
begin
  foreach t in array array['media_generation_jobs','audio_generations','render_jobs','project_assets','video_timelines','subtitle_tracks','render_artifacts'] loop
    if not exists(select 1 from pg_constraint where conname=t||'_run_scope_fk') then
      execute format('alter table public.%I add constraint %I foreign key (production_run_id,workspace_id,project_id) references public.production_runs(id,workspace_id,project_id) on delete set null (production_run_id)',t,t||'_run_scope_fk');
    end if;
    if not exists(select 1 from pg_constraint where conname=t||'_parent_step_scope_fk') then
      execute format('alter table public.%I add constraint %I foreign key (parent_step_id,production_run_id,workspace_id,project_id) references public.production_run_steps(id,production_run_id,workspace_id,project_id) on delete set null (parent_step_id)',t,t||'_parent_step_scope_fk');
    end if;
  end loop;
end $$;

create index if not exists agent_tasks_run_step_idx on public.agent_tasks(production_run_id,parent_step_id);
create index if not exists media_generation_jobs_run_step_idx on public.media_generation_jobs(production_run_id,parent_step_id);
create index if not exists audio_generations_run_step_idx on public.audio_generations(production_run_id,parent_step_id);
create index if not exists render_jobs_run_step_idx on public.render_jobs(production_run_id,parent_step_id);
create index if not exists project_assets_run_step_idx on public.project_assets(production_run_id,parent_step_id);
create index if not exists video_timelines_run_step_idx on public.video_timelines(production_run_id,parent_step_id);
create index if not exists subtitle_tracks_run_step_idx on public.subtitle_tracks(production_run_id,parent_step_id);
create index if not exists render_artifacts_run_step_idx on public.render_artifacts(production_run_id,parent_step_id);

alter table public.production_run_steps enable row level security;
alter table public.production_run_step_dependencies enable row level security;
drop policy if exists production_run_steps_workspace_access on public.production_run_steps;
create policy production_run_steps_workspace_access on public.production_run_steps
for all to graphytion_api,graphytion_runtime
using (private.graphytion_is_workspace_member(workspace_id))
with check (private.graphytion_is_workspace_member(workspace_id));
drop policy if exists production_run_step_dependencies_workspace_access on public.production_run_step_dependencies;
create policy production_run_step_dependencies_workspace_access on public.production_run_step_dependencies
for all to graphytion_api,graphytion_runtime
using (private.graphytion_is_workspace_member(workspace_id))
with check (private.graphytion_is_workspace_member(workspace_id));

grant select,insert,update,delete on public.production_run_steps,
  public.production_run_step_dependencies to graphytion_api,graphytion_runtime;
grant select,insert,update,delete on public.agent_tasks,
  public.media_generation_jobs,public.audio_generations,public.render_jobs,
  public.project_assets,public.video_timelines,public.subtitle_tracks,
  public.render_artifacts to graphytion_api,graphytion_runtime;

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
      when j.status in ('queued','retry_wait','pending') then 'ready'
      else s.status end,
      completed_at=case when j.status in ('completed','failed','provider_unavailable','cancelled') then coalesce(s.completed_at,now()) else s.completed_at end,
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

revoke all on function private.graphytion_sync_production_run(uuid) from public,anon,authenticated;
grant execute on function private.graphytion_sync_production_run(uuid) to graphytion_api,graphytion_runtime;

commit;
