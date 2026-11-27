-- Index the referencing side of the new canonical agent registry FK.
create index if not exists agent_tool_registry_agent_key_idx
  on public.agent_tool_registry(agent_key);
