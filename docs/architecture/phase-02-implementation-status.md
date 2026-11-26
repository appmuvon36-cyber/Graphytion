# Phase 02 Implementation Status

**Phase:** Supabase Auth, Profiles, Workspace Membership, RBAC and Project CRUD  
**Repository:** `appmuvon36-cyber/Graphytion`  
**Branch:** `main`  
**Supabase:** `xtjwmezfzexvupbfsdqt` (Graphytion, ap-northeast-1)  
**Status:** Core schema and security migrations applied. Finalization code is committed; Production runtime, provider configuration, pending migrations and real-account E2E are NOT verified. Do not mark Phase 02 complete.

## Implemented in the repository

### API runtime and database boundary

- Production Pydantic validation for required server secrets, project-specific Supabase URL/JWT issuer/JWKS, dedicated `graphytion_api` database login, PostgreSQL TLS, managed Redis TLS, HTTPS CORS allowlist, BFF shared secret and Resend configuration.
- Readiness checks PostgreSQL, Redis, Supabase Auth, JWT/JWKS signing-key availability and private Storage as separate dependencies.
- Database connection uses a secret-safe URL accessor and a named SQLAlchemy application connection.
- Per-request authenticated subject is set in PostgreSQL session claims and cleared before pooled connection release. This supports tenant RLS rather than using a superuser or RLS-bypass role.
- Liveness and readiness endpoints are separate. Readiness checks PostgreSQL, Redis, Supabase Auth and private Storage independently and returns 503 if any dependency is unavailable.
- Supabase Auth and Storage adapters expose real connectivity probes. Service-role key remains server-side only.

### Invitation lifecycle

- Resend adapter sends a secure, expiring, single-use invitation link. Raw token is hashed in the database and only exists in memory during email delivery.
- API responses and Admin UI no longer return or display raw invitation tokens.
- Provider idempotency key, send-attempt tracking, delivery state, explicit resend eligibility, cancellation, duplicate prevention and audit events are implemented.
- Signed Resend webhook validates Svix signature and replay timestamp, then updates sent/delivered/delayed/bounced/complained/failed states.
- Production delivery is not proven until owner configures a verified sender domain, API key and webhook signing secret.

### Browser session boundary

- Customer Web and Admin use same-origin Next.js BFF routes.
- Login/signup/verification token exchange is restricted to requests carrying the server-only BFF shared secret.
- Access and refresh tokens are set as host-only HttpOnly cookies; production cookies are Secure, SameSite=Lax and Path=/.
- Refresh and logout are handled server-side. CSRF uses a separate random cookie, request header and exact Origin check.
- Legacy `sessionStorage` and `localStorage` token persistence was removed from the inspected Customer Studio and Admin Control Plane components. A repository scan of the 16 Web/Admin/API-client TypeScript files found no `sessionStorage` or `localStorage` references.
- Browser API client no longer accepts or injects bearer tokens; only the same-origin BFF reads HttpOnly cookies and attaches upstream Authorization. BFF auth responses expose only user ID/email, and the verification callback is non-cacheable with a no-referrer policy.
- Supabase confirmation/recovery email templates must be changed to the server-side token-hash callback; the existing project settings were not changed.

## Production migrations applied

| Migration | Purpose | Supabase migration version |
|---|---|---|
| `202611260001_identity_workspace_projects` | Identity, workspace, membership, invitation, project, RLS and private avatar bucket | `20261126095034` |
| `202611260002_security_hardening` | Private RLS helper functions and restricted execution | `20261126095112` |
| `202611260003_least_privilege_grants` | Remove broad anon/authenticated table grants | `20261126095238` |

The following additive migrations are committed to `main` but have NOT been applied to Production:

| Migration | Purpose | Status |
|---|---|---|
| `202611260004_invitation_email_delivery.sql` | Invitation provider delivery status, attempt count, provider ID and webhook state columns | Awaiting explicit Production migration authorization |
| `202611260005_fastapi_runtime_role_rls.sql` | `graphytion_runtime` / `graphytion_api` roles, profile email sync, scoped RLS policies, invitation webhook policy and least-privilege column grants | Awaiting explicit Production migration authorization |

The runtime role migration deliberately creates `graphytion_api` as NOLOGIN. It now grants only the operations/columns used by FastAPI, removes the legacy `service_role` grants from public business tables, and leaves the service-role key for the private Storage adapter only. After migration approval/application, the project owner must set a unique password and enable LOGIN out-of-band, then set the server `DATABASE_URL`. No password is committed.

## Latest live Supabase inspection

Project `xtjwmezfzexvupbfsdqt` reported `ACTIVE_HEALTHY`, PostgreSQL 17.12.0.002.

- Migration history contains exactly the three applied migrations above.
- Auth users: **0**
- Profiles: **0**
- Workspaces: **0**
- Video projects: **0**
- Invitations: **0**
- Roles `graphytion_runtime` and `graphytion_api`: not present yet.
- Invitation delivery columns from migration 004: not present yet.

No real account or production test record was created.

## Owner-gated completion work

1. Explicitly authorize applying migrations `202611260004` and `202611260005` to Supabase Production. They are additive and contain no DROP/DELETE data operations, but are not applied under the current no-migration-without-authorization rule.
2. After migration 005, enable LOGIN and set a unique password for `graphytion_api` in Supabase SQL editor/secret manager; configure API `DATABASE_URL` with this role and TLS.
3. Configure API hosting secrets: `APP_ENV`, `APP_PUBLIC_URL`, `CORS_ORIGINS`, Supabase anon/service keys, `BFF_SHARED_SECRET`, database URL, managed `rediss://` URL, Resend API key, verified sender and webhook secret.
4. Configure both Next.js services with their own `APP_PUBLIC_URL`, server-only `GRAPHYTION_API_URL` and the matching `GRAPHYTION_BFF_SHARED_SECRET`.
5. Configure Supabase Auth Site URL, redirect allowlist and signup/recovery templates to call `/api/auth/callback?token_hash={{ .TokenHash }}&type=...`.
6. Configure Resend sender domain and register `https://<api-domain>/api/v1/webhooks/resend`.
7. After deployment is separately authorized, verify `/api/v1/ready` from the real API runtime. No hosting secrets or deployments were changed by this work.
8. Use a real Graphytion user who completes email verification to run Auth, session, profile, workspace, invitation, all RBAC roles, project CRUD, tenant-isolation/IDOR, CSRF, expiry/revocation and audit/database consistency checks. No user email was available in this task, so no account was created.

## Current completion gate

| Gate | Status |
|---|---|
| Phase 01 foundation/build gates | Complete (previous passing CI evidence) |
| Existing Phase 02 schema and RLS migrations | Applied and verified |
| Production runtime secrets/connectivity | Not configured/verified |
| Dedicated FastAPI DB login | Migration prepared; role not created yet |
| Resend email and delivery webhooks | Adapter implemented; provider not configured or tested |
| HttpOnly BFF and CSRF | Code implemented; production domain/runtime not deployed or browser-tested |
| Real verified-user E2E and RBAC/IDOR tests | Not run; Production Auth user count is zero |
| Phase 02 overall | **OPEN — NOT COMPLETE** |

## Data safety

- No production user, workspace, project or invitation was created, changed or deleted during this finalization work.
- No production secrets were read or changed.
- Migrations 004 and 005 were not applied.
- No staging environment or deployment was created or triggered.
- Prefer forward corrective migrations; do not drop existing Phase 02 schema as a rollback shortcut.

See [Phase 02 Production Runtime Runbook](../operations/phase-02-production-runtime-runbook.md) for the exact owner-side configuration steps.
