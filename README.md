# Weave CLOUD SPACE

Weave is a multi-tenant school management SaaS for running core school operations across administrators, teachers, parents, students, and platform superadmins. The repository is a monorepo with a FastAPI backend and a React/Vite frontend.

## Supported Roles

- **Superadmin**: manages platform-wide controls, tenant oversight, analytics, and operational monitoring.
- **Tenant admin**: manages one school tenant, including users, students, classes, subjects, announcements, billing, onboarding, and academic workflows.
- **Teacher**: manages assigned classes, subjects, attendance, assignments, results, and student academic views.
- **Parent**: views linked children, reports, results, announcements, and student progress.
- **Student**: accesses assigned subjects, reports, profile flows, and student-specific academic information.

## Architecture

- `backend/` contains the FastAPI application, SQLAlchemy models/repositories, Pydantic schemas, services, routers, Alembic migrations, Redis cache utilities, and ARQ workers.
- `frontend/` contains the React application built with Vite, React Router, feature modules, shared UI, and service clients.
- PostgreSQL is the system of record.
- Redis supports caching, rate limiting, background queues, and worker health keys.
- Alembic owns schema migrations.
- Railway hosts the backend API, PostgreSQL, Redis, and worker services.
- Vercel hosts the frontend.

## Repository Structure

```text
/
├── backend/              FastAPI API, Alembic, tests, backend scripts
├── frontend/             React/Vite frontend
├── docs/                 Durable engineering documentation
├── .github/              Pull request template and CI workflows
├── .editorconfig         Shared editor defaults
├── .gitignore            Repository-wide ignore rules
├── CONTRIBUTING.md       Development and review workflow
├── SECURITY.md           Private vulnerability reporting process
└── docker-compose.yml    Local Redis/API orchestration
```

## Backend Stack

- FastAPI
- SQLAlchemy async ORM
- Pydantic and Pydantic Settings
- Alembic
- PostgreSQL via `asyncpg`
- Redis
- ARQ
- Pytest
- Ruff and Pyright

## Frontend Stack

- React
- Vite
- React Router
- Tailwind CSS
- Lucide React
- Recharts
- ESLint
- Node test runner

## Local Development

Environment values are managed separately and must not be committed. Do not put secrets, credentials, generated login files, or real user data in documentation, source files, tests, or CI configuration.

### Backend Setup

```bash
cd backend
cp .env.example .env
# Set DATABASE_URL to an empty or initialized local PostgreSQL database.
uv sync
```

If a deployment target still uses `requirements.txt`, treat it as compatibility output rather than an independent source of truth.

### Frontend Setup

```bash
cd frontend
cp .env.example .env.local
npm ci
```

### Start Redis and API with Docker Compose

```bash
docker compose up redis backend
```

### Start the API Locally

```bash
cd backend
uv run uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

### Start ARQ Workers

The general worker handles lightweight and recurring work. The heavy worker serializes imports and progression so they cannot compete for database capacity.

The general worker also probes up to eight pending Paystack term payments every ten minutes, with cooldown state persisted on each transaction. It retries recently abandoned checkouts for seven days to detect delayed settlements. Normal pending payments use the existing idempotent settlement path; paid abandoned checkouts are recorded for manual reconciliation rather than activating an outdated plan. Paystack webhooks remain the primary payment notification mechanism. This is a recovery job, not a replacement for webhook delivery monitoring.

Checkout expiry is provider-aware: after the 30-minute local TTL, the lifecycle job (and replacement checkout flow) checks the current Paystack status before abandoning a transaction. Confirmed successes settle using the existing idempotent entitlement path; failed/abandoned gateway states can expire. A gateway-level pending state gets a two-hour grace window, and provider outages, malformed/mismatched responses, or settlement conflicts defer expiry. The expiry sweep checks at most eight transactions per run and rotates based on last-attempt metadata. A settled checkout is never replaced simply because its original callback did not complete.

```bash
cd backend

# Email delivery, attendance retention, and subscription reconciliation
uv run arq app.core.queue.general_worker.WorkerSettings

# Confirmed student bulk imports and academic-session progression
uv run arq app.core.queue.heavy_worker.WorkerSettings
```

Recommended initial database pool values:

```text
API:            DB_POOL_SIZE=5  DB_MAX_OVERFLOW=3
General worker: DB_POOL_SIZE=2  DB_MAX_OVERFLOW=1
Heavy worker:   DB_POOL_SIZE=1  DB_MAX_OVERFLOW=1
```

See `docs/background-workers.md` for the deployment sequence and health keys.

### Start the Frontend

```bash
cd frontend
npm run dev
```

## Validation Commands

### Backend

```bash
cd backend
uv run --with ruff ruff check .
uv run --with ruff ruff format --check .
uv run --with pyright pyright app
uv run alembic heads
uv run alembic history
uv run alembic upgrade head
uv run alembic check
uv run pytest tests/unit
uv run pytest tests/integration
uv run python -c "from app.main import app; print(app.title)"
uv run python -c "from app.core.queue.general_worker import WorkerSettings; print(WorkerSettings.queue_name)"
uv run python -c "from app.core.queue.heavy_worker import WorkerSettings; print(WorkerSettings.queue_name)"
```

### Frontend

```bash
cd frontend
npm run lint
npm run test
npm run build
npm run check
```

## Health Checks

- `/health/live` proves that the API process is running.
- `/health` and `/health/ready` verify PostgreSQL and Redis and return HTTP 503 when either dependency is unavailable.
- `weave:queue:general:health` proves the general worker is alive.
- `weave:queue:heavy:health` proves the heavy worker is alive.

Use `/health/ready` for deployment readiness and `/health/live` for process liveness.

## PostgreSQL and Alembic

`20260911_initial_schema` is the single frozen fresh-database baseline, consolidated on 2026-10-03 for migration to a new repository. It includes all schema changes through CBT AI idempotency and has no predecessor. The former incremental revision files have been removed.

Use this history only with a new, empty PostgreSQL database. Existing databases stamped with a removed revision cannot upgrade using this history; retain their original migration history and handle their transition separately. Do not stamp or reset an existing database automatically. After the new repository starts using this baseline, keep it frozen and add revisions for future changes. A downgrade to `base` deletes application tables and data; rollback for an existing deployment requires its original code/history and a verified backup.

On application startup, Weave acquires a PostgreSQL transaction advisory lock and inspects the `public` schema. An empty database is initialized from the complete SQLAlchemy model registry, required PostgreSQL extensions are created, and `alembic_version` is stamped to the baseline in the same transaction. Concurrent first starts therefore serialize safely.

If all model tables already exist, startup does not call `create_all()`, stamp, drop, or recreate anything. A partial schema—or an Alembic marker without the application tables—is rejected with an explicit startup error because silently repairing it could hide drift or data loss. `create_all()` is only the first-install mechanism; every schema change after the baseline requires Alembic.

The frozen baseline also supports migration-only provisioning of an empty PostgreSQL database:

```bash
cd backend
uv run alembic upgrade head
```

For each future schema change:

```bash
cd backend
uv run alembic revision --autogenerate -m "describe the schema change"
# Review the generated upgrade and downgrade before running either.
uv run alembic upgrade head
uv run alembic heads
uv run alembic current
uv run alembic check
```

Never stamp an existing database merely to silence Alembic. Stamping is valid only after its schema has been independently verified to match the target revision. Database resets and history rewrites are development-only operations and must never target staging or production.

Before production rollout, run migrations against a current production-like database, verify critical workflows, and confirm backup and restore procedures.

## Production Configuration

Production-like environments fail startup when required infrastructure or security settings are missing. At minimum, configure:

- strong independent `SECRET_KEY` and `BULK_IMPORT_RESULT_ENCRYPTION_KEY` values;
- PostgreSQL and Redis URLs;
- explicit HTTPS CORS origins and frontend URL;
- trusted proxy headers and the correct trusted proxy hop count;
- an HTTPS email provider endpoint or complete SMTP credentials;
- durable R2 media storage in production;
- conservative database pool sizes for each deployed process.

Production logs are emitted as single-line JSON to standard output for Railway collection. Development keeps readable console output and rotating `backend/logs/app.log` files.

Refresh and logout requests use the HttpOnly refresh cookie and require both an approved browser origin and the `X-Weave-CSRF: 1` request header.

Student setup codes created by bulk import are encrypted at rest and available for access-slip generation only for the configured retention window.

## CBT student hostname resolution (portable offline client setup)

After pairing and activating HTTPS on the local CBT server, administrators can
generate an offline Windows **or** Linux student-PC setup package on a server
running the corresponding operating system:

```bash
weave network client export --output <directory>
```

Copy the exported ZIP to a USB drive, extract it on each student computer and
run `WEAVE-CBT-Client-Setup.exe` (Windows; approve UAC) or
`sudo ./weave-cbt-client-setup` (Linux) from the extracted folder alongside
`weave-client.json`. The utility uses the saved school LAN IP and paired HTTPS
hostname, safely updates its own managed hosts entry, retains its previous
configuration for subsequent domain/IP changes, and automatically flushes the
available DNS cache after a change. Resolution and HTTPS checks are reported
separately. No Python, Docker, WSL, or WEAVE CLI installation is needed on
student PCs.

Previously **manual/unmanaged** hosts entries are not overwritten; resolve any
conflict deliberately. The optional CoreDNS and router/DHCP solution remains
available for centrally managed school networks. See
[CBT student hostname setup and manual fallback](docs/cbt-manual-local-dns.md).

## Deployment

- Backend API: Railway
- PostgreSQL: Railway
- Redis: Railway
- General worker: Railway
- Heavy worker: Railway
- Frontend: Vercel

### Release Checklist

1. Remove or rotate any credentials that have appeared in repository history.
2. Configure all production environment variables and verify startup validation.
3. Run backend and frontend CI, including fresh migration upgrades and integration tests.
4. Deploy migrations before application processes that require the schema.
5. Deploy the API, general worker, and heavy worker.
6. Verify `/health/ready` and both ARQ worker health keys.
7. Confirm the subscription reconciliation cron executes successfully.
8. Run authentication, invitation, student creation, bulk-import, academic-session, report-card, and notification smoke tests in staging.
9. Verify Railway receives structured API and worker logs with service and release context.
10. Promote staging only after test evidence and rollback steps are recorded.

## Branching and Pull Requests

Use short-lived branches and Conventional Commit-style messages:

```text
feat:
fix:
refactor:
test:
docs:
chore:
ci:
perf:
```

Open pull requests with test evidence, migration impact, environment-variable impact, deployment impact, and rollback considerations. Do not push directly to `master`.
