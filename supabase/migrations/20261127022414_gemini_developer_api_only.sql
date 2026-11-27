-- Make Gemini Developer API the only supported image/video generation provider.
-- Existing Agent Platform rows are retained and normalized to the same Gemini provider identity.
begin;

update public.media_generation_jobs
set provider_key='gemini', updated_at=now()
where provider_key='google_agent_platform';

alter table public.media_generation_jobs
  drop constraint if exists media_generation_jobs_provider_key_check;

alter table public.media_generation_jobs
  add constraint media_generation_jobs_provider_key_check
  check (provider_key in ('gemini'));

commit;
