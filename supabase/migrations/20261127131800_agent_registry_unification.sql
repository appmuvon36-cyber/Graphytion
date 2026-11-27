-- Persist the canonical registry for all currently executable creative agents.
begin;
create table if not exists public.agent_registry (
  agent_key text primary key,
  display_name text not null,
  stage_key text not null check (stage_key in ('brief','script','storyboard','scene')),
  execution_handler text not null check (execution_handler in (
    'creative_pipeline.interpret_prompt',
    'creative_pipeline.write_script',
    'creative_pipeline.direct_story',
    'creative_pipeline.direct_storyboard',
    'creative_pipeline.regenerate_scene'
  )),
  output_schema_key text not null,
  prompt_version integer not null check (prompt_version>0),
  permission_key text not null default 'project.update',
  is_enabled boolean not null default true,
  configuration jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists agent_registry_stage_enabled_idx
  on public.agent_registry(stage_key,is_enabled,agent_key);
insert into public.agent_registry(agent_key,display_name,stage_key,execution_handler,output_schema_key,prompt_version,permission_key,is_enabled)
values
 ('prompt_interpreter','Prompt Interpreter','brief','creative_pipeline.interpret_prompt','CreativeBriefOutput',1,'project.update',true),
 ('scriptwriter','Scriptwriter','script','creative_pipeline.write_script','ScriptOutput',1,'project.update',true),
 ('story_director','Story Director','storyboard','creative_pipeline.direct_story','StoryArcOutput',1,'project.update',true),
 ('storyboard_director','Storyboard / Visual Director','storyboard','creative_pipeline.direct_storyboard','StoryboardOutput',1,'project.update',true),
 ('scene_regenerator','Scene Visual Director','scene','creative_pipeline.regenerate_scene','StoryboardSceneOutput',1,'project.update',true)
on conflict(agent_key) do update set
 display_name=excluded.display_name,stage_key=excluded.stage_key,
 execution_handler=excluded.execution_handler,output_schema_key=excluded.output_schema_key,
 prompt_version=excluded.prompt_version,permission_key=excluded.permission_key,
 is_enabled=excluded.is_enabled,updated_at=now();

alter table public.agent_registry enable row level security;
drop policy if exists agent_registry_backend_read on public.agent_registry;
create policy agent_registry_backend_read on public.agent_registry
  for select to graphytion_api,graphytion_runtime using (true);
revoke all on public.agent_registry from public,anon,authenticated;
grant select on public.agent_registry to graphytion_api,graphytion_runtime;

do $$
begin
  if not exists(select 1 from pg_constraint where conname='agent_tool_registry_agent_registry_fk') then
    alter table public.agent_tool_registry
      add constraint agent_tool_registry_agent_registry_fk
      foreign key(agent_key) references public.agent_registry(agent_key)
      on update cascade on delete restrict;
  end if;
end $$;
commit;
