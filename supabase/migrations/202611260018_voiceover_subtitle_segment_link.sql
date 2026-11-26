-- Optional voiceover-to-subtitle segment linkage for selective regeneration.
begin;
alter table public.audio_generations
  add column if not exists subtitle_segment_id uuid references public.subtitle_segments(id) on delete set null;
create index if not exists audio_generations_subtitle_segment_idx
  on public.audio_generations(subtitle_segment_id) where subtitle_segment_id is not null;
commit;
