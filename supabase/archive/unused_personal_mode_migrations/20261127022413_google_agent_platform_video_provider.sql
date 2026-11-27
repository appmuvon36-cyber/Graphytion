-- Add Google Agent Platform as the explicit video provider identity.
begin;
alter table public.media_generation_jobs
  drop constraint if exists media_generation_jobs_provider_key_check;
alter table public.media_generation_jobs
  add constraint media_generation_jobs_provider_key_check
  check (provider_key in ('gemini','google_agent_platform'));
commit;
