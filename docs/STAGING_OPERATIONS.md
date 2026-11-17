# Staging operations

Run `docker compose -f docker-compose.staging.yml up -d --build` on the protected staging container host after creating `.env.staging` from `.env.example`. The file must contain the staging PostgreSQL URL, session secret, private R2 credentials, and ClamAV settings; never commit it.

Container health changes should alert through the staging platform. Alert when any container is unhealthy for two checks, when `/api/admin/worker-health` reports `degraded`, or when `max_release_lag_seconds` exceeds 120. Route alerts to the approved operations channel.

The scan worker writes uploads under the private `quarantine/` prefix, performs content disarm and ClamAV scanning, deletes the quarantine object after a clean result, and only then creates an approval request. Failed objects stay inaccessible and require an audited operator review.

The digest worker builds durable delivery records in `notification_digests`. This prototype records delivery in the outbox; connecting an email provider remains a separate backend integration and must respect user preferences.

The R2 workflow requires a GitHub `staging` environment with the four `PACT_R2_TEST_*` secrets. The bucket must be private, isolated from production, and credentials must be restricted to object read/write/delete for that bucket.

## Accounts and sign-in

Sign-in is local accounts with a password plus a mandatory authenticator-app code (TOTP). Development
personas are unavailable outside development.

Required settings outside development (startup fails without them):

- `PACT_TOTP_ENCRYPTION_KEY`: Fernet key that encrypts authenticator seeds at rest. Generate with
  `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"`. Store it
  with the other secrets. **Losing or rotating it invalidates every enrolled authenticator** (all users would
  need reset links).
- `PACT_COOKIE_SECURE=true`: the session cookie is HTTPS-only.

Bootstrap the first Program Administrator on the server (there is no HTTP route for this):

    cd backend
    python -m app.accounts_cli create-admin --username <name> --display-name "<Full Name>" --email <email>

It prints a one-time `/setup#token=…` path, valid 72 hours. Prefix it with the site origin and deliver it
through an approved channel. After that, the administrator creates further users and issues their setup
links from **Users** in the application. If an administrator loses access:
`python -m app.accounts_cli reset-link --username <name>`.

Session and lockout defaults: 8-hour session, 30-minute idle timeout, 5 failed attempts lock the account
for 15 minutes. A Program Administrator or Security/Operations Administrator can unlock accounts and end
sessions from **Users**.

## Scenario release plans

Everything a cohort can receive (case evidence injects, staged document blocks, challenges, debriefs, and
instructor-only answer keys) is defined in a **release plan** attached to a scenario version.

1. **Author** (Curriculum Editor, under **Scenarios**): add items, each with an audience and a trigger:
   instructor release, scheduled course day/time (cohort-local), lesson stage (e.g. "M04 taught"), or after
   another item. Approved versions are locked; clone to a new version to change them.
2. **Approve** (Content Approver): approves the plan as a package. The approval pins the plan's SHA-256 and is
   refused if the plan changed after submission. Evidence injects still need their own content approval;
   scored challenges stay blocked until the instrument is authorized for scored use.
3. **Activate** (Program Administrator, under **Cohorts**): attaches an approved version to a cohort and
   creates its case, assignments and release timeline. A cohort runs one version for the whole course.
4. **Run** (Instructors, under **Release Plan**): release now, hold, resume, or withdraw with a reason.
   Releases notify students; withdrawals hide the material but keep its history. Answer keys are never
   released to students. Scheduled items are opened by the release-scheduler worker (`python -m
   app.scheduler_worker`) and also whenever the plan is viewed.

The platform's case is **HARBORLINE** (v0.3 reinforcing exercise suite). Its evidence library, injects,
E03 workspaces, exercise packets, instructor keys and K01/K02 items are read from
`pact curriculum/PACT_Instructor_Exercise_Master_v0.3/` at install time. GLASS HARBOR is retired.

A development database seeded earlier can be converted without re-seeding (keeps accounts, submissions and
history; moves cohorts from GLASS HARBOR to HARBORLINE; clears only drafts written for the old workspaces).
It is safe to rerun:

    cd backend
    alembic upgrade head
    python -m app.seed --harborline

**Course Materials** (sidebar) is where students download packets released to their cohort and staff
download instructor-only materials. Download links are short-lived, tied to the user, and re-checked
when used; withdrawing a release stops further downloads.
