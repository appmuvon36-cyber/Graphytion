# Graphytion Phase 02 — Production Runtime Runbook

**Repository:** `appmuvon36-cyber/Graphytion`  
**Branch:** `main`  
**Supabase project:** `xtjwmezfzexvupbfsdqt`  
**Status:** Application code prepared; external runtime secrets, two additive migrations and real-account E2E remain owner-gated. No deployment or secret mutation was performed.

## 1. Runtime configuration

Configure secrets in the hosting provider's server-side environment manager. Do not put production values in Git, browser-exposed `NEXT_PUBLIC_*` variables, build logs, or chat.

### FastAPI service

Required variables:

- `APP_ENV=production`
- `APP_PUBLIC_URL=https://<customer-web-domain>`
- `CORS_ORIGINS=https://<customer-web-domain>,https://<admin-domain>`
- `SUPABASE_URL=https://xtjwmezfzexvupbfsdqt.supabase.co`
- `SUPABASE_JWT_ISSUER=https://xtjwmezfzexvupbfsdqt.supabase.co/auth/v1`
- `SUPABASE_JWKS_URL=https://xtjwmezfzexvupbfsdqt.supabase.co/auth/v1/.well-known/jwks.json`
- `SUPABASE_ANON_KEY` — Supabase publishable/anon key, server-side only.
- `SUPABASE_SERVICE_ROLE_KEY` — server-side only; used only by the FastAPI Storage adapter.
- `DATABASE_URL` — PostgreSQL TLS connection using the dedicated `graphytion_api` login, not `postgres` or `supabase_admin`.
- `BFF_SHARED_SECRET` — high-entropy secret, at least 32 characters.
- `INVITATION_EMAIL_PROVIDER=resend`
- `RESEND_API_KEY`
- `RESEND_WEBHOOK_SECRET`
- `INVITATION_FROM_EMAIL` — sender identity on a domain verified by Resend.

The API rejects production startup configuration when a critical setting is absent, the database user is not `graphytion_api`, TLS is not required, Supabase project/JWT URLs mismatch, CORS includes wildcards/non-HTTPS origins, or the sender is a placeholder domain.

### Customer Web and Admin Next.js services

Each frontend requires server-only variables:

- `GRAPHYTION_API_URL=http://graphytionapi.railway.internal:8000/api/v1` when Web and API share the Railway private network. The BFF accepts HTTP only for the `.railway.internal` host; public API integrations and webhooks must use the HTTPS API domain.
- `GRAPHYTION_BFF_SHARED_SECRET` — exactly the same secret as FastAPI `BFF_SHARED_SECRET`.
- `APP_PUBLIC_URL` — the exact origin of that frontend (customer domain for Web, admin domain for Admin).

Do not configure `NEXT_PUBLIC_API_BASE_URL` to point at FastAPI. Browser requests must use the same-origin `/api` BFF. Host-only cookies are issued separately for each frontend origin.

### API replica constraint

The current authentication rate limiter is process-local to avoid an external cache dependency. Keep the FastAPI service at one replica until a shared PostgreSQL-backed rate-limit store is implemented and migrated. PostgreSQL worker queues remain safe for multiple worker replicas through transactional job leases.

## 2. Database runtime role

Migration `202611260005_fastapi_runtime_role_rls.sql` creates:

- `graphytion_runtime`: explicitly NOLOGIN privilege group, inherits the Supabase `authenticated` role and has no superuser, database-creation, role-creation, schema-create or RLS-bypass privileges.
- `graphytion_api`: explicitly NOLOGIN database identity, member of `graphytion_runtime`.
- Runtime table grants are limited to the columns/operations required by FastAPI. Legacy `service_role` access to public business tables is revoked; its key remains server-side for the private Storage adapter only.

After the migration is explicitly approved and applied, the project owner must set a strong password and enable login out-of-band in the Supabase SQL editor/secret manager:

```sql
ALTER ROLE graphytion_api LOGIN PASSWORD '<unique-generated-secret>';
```

Store that password only in the API secret manager and set `DATABASE_URL` to the `graphytion_api` login with `ssl=require`. Do not grant `BYPASSRLS`. FastAPI sets and clears the authenticated subject on its pooled database session so tenant RLS policies remain active.

## 3. Supabase Auth callback configuration

In Supabase Authentication settings:

1. Set the Site URL to the customer web HTTPS origin.
2. Add only the real customer and admin redirect origins to the redirect allowlist.
3. Update the signup/confirmation email template to route the one-time token hash through the server callback:
   `{{ .SiteURL }}/api/auth/callback?token_hash={{ .TokenHash }}&type=signup`
4. Update the password recovery template similarly, using `type=recovery`.
5. Confirm the callback path is reachable on the customer web deployment.

The BFF verifies the token hash server-side and sets HttpOnly cookies. Do not use the legacy implicit-flow fragment containing `access_token` or `refresh_token`.

## 4. Resend invitation email

1. Verify the sender domain in Resend and configure the sender identity.
2. Store `RESEND_API_KEY` and `RESEND_WEBHOOK_SECRET` in the FastAPI secret manager.
3. Register the webhook URL `https://<api-domain>/api/v1/webhooks/resend` for sent, delivered, delayed, bounced, complained and failed events.
4. Verify the webhook signature secret matches the Resend endpoint.
5. Invitation status `sent` means the provider accepted the message. Only signed provider webhooks can change it to delivered, delayed, bounced or complained.
6. A resend rotates the invitation token and is allowed only after a provider failure or invitation expiry. Bounced/complained addresses are blocked pending correction.

No message is considered delivered merely because the API request succeeded.

## 5. Session and CSRF behavior

- Access and refresh tokens are stored only in host-only HttpOnly cookies.
- Production cookies use Secure, SameSite=Lax and Path=/; no Domain attribute is set.
- CSRF token is a separate non-HttpOnly random cookie, sent in `X-CSRF-Token`; unsafe requests require an exact Origin match, with an exact Referer-origin fallback only when Origin is absent.
- BFF forwards the client address to FastAPI only alongside the server-only shared secret; rate limiting trusts that address only after validating the BFF secret, preventing all browser users from sharing the API gateway IP bucket.
- `APP_ENV` defaults to `production`; local development and CI must explicitly set `APP_ENV=local` so missing deployment configuration cannot silently bypass production validation.
- Browser API client cannot attach bearer tokens; the BFF alone reads HttpOnly cookies and injects Authorization for the FastAPI upstream. Auth callback responses are `no-store` and `no-referrer`.
- Refresh is server-side and uses the HttpOnly refresh cookie. Logout attempts to revoke the current session before clearing cookies.
- The shared BFF secret protects signup, login, refresh and verification token-exchange endpoints from direct browser calls.
- Configure the exact APP_PUBLIC_URL for each Next.js deployment. Do not share cookies across customer/admin hosts.

## 6. Readiness and verification

FastAPI exposes:

- `GET /api/v1/health` — liveness only.
- `GET /api/v1/ready` — independent database, Supabase Auth, JWT/JWKS signing-key and Storage checks; returns 503 if any dependency is unavailable.

After environment configuration and the two pending migrations, verify using an account created through the real signup flow and confirmed through the actual email link. Then verify login, refresh, logout, recovery, profile, workspace ownership, invitations, role permissions, project lifecycle, cross-workspace IDOR denial, CSRF rejection, revoked/expired tokens, audit rows and database counts.

Do not seed production with synthetic users or sample workspaces. Record the account owner-approved for the test and use only clearly identified test records.

## 7. Owner-gated actions still required

- Explicit approval to apply migrations `202611260004_invitation_email_delivery.sql` and `202611260005_fastapi_runtime_role_rls.sql` to Supabase Production.
- Production web, admin and API domain names.
- Production secret-manager access to set API/BFF/DB/Resend values.
- Resend verified sender domain, API key and webhook signing secret.
- Supabase Auth Site URL, redirect allowlist and email templates.
- Hosting-provider access and explicit deployment authorization.
- A real Graphytion user who can complete the email verification link for E2E.

Until those actions are completed, do not label Phase 02 production runtime, invitation delivery or end-to-end verification complete.
