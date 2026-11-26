-- Graphytion Phase 02: persist provider-backed invitation delivery state.
begin;

alter table public.workspace_invitations
  add column if not exists delivery_status text not null default 'pending',
  add column if not exists delivery_attempts integer not null default 0,
  add column if not exists provider_message_id text,
  add column if not exists sent_at timestamptz,
  add column if not exists last_delivery_attempt_at timestamptz,
  add column if not exists last_delivery_error text;

do $delivery_constraints$
begin
  if not exists (
    select 1 from pg_constraint
    where conname='workspace_invitations_delivery_status_check'
      and conrelid='public.workspace_invitations'::regclass
  ) then
    alter table public.workspace_invitations
      add constraint workspace_invitations_delivery_status_check
      check (delivery_status in ('pending','sent','delivered','delivery_delayed','bounced','complained','failed'));
  end if;
  if not exists (
    select 1 from pg_constraint
    where conname='workspace_invitations_delivery_attempts_check'
      and conrelid='public.workspace_invitations'::regclass
  ) then
    alter table public.workspace_invitations
      add constraint workspace_invitations_delivery_attempts_check
      check (delivery_attempts >= 0);
  end if;
end
$delivery_constraints$;

create index if not exists workspace_invitations_delivery_status_idx
  on public.workspace_invitations(delivery_status, last_delivery_attempt_at)
  where accepted_at is null and cancelled_at is null;

comment on column public.workspace_invitations.delivery_status is
  'Provider acceptance state; sent means Resend accepted the message, not inbox delivery.';
comment on column public.workspace_invitations.last_delivery_error is
  'Redacted provider error category only; never store recipient credentials or invitation tokens.';

commit;
