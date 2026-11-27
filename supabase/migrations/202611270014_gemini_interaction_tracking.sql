-- Persist the Gemini Developer API interaction ID for asynchronous video jobs.
-- This is additive and preserves existing generation records.
alter table public.media_generation_jobs
    add column if not exists provider_operation_id text;

create index if not exists idx_media_generation_provider_operation
    on public.media_generation_jobs (provider_key, provider_operation_id)
    where provider_operation_id is not null;
