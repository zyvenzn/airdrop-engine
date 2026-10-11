# Airdrop Engine

Telegram bot and Mini App backend for points farming, task campaigns, referrals, and future token-reward eligibility.

> **Development status:** early scaffold. Do not deploy to production or open public farming yet.

## Stack
- Python 3.12, FastAPI, aiogram 3
- PostgreSQL, SQLAlchemy 2, Alembic
- Redis for distributed rate limiting
- Next.js + TypeScript (planned for Mini App and admin UI)
- pytest and GitHub Actions CI

## Local setup

1. Install Python 3.12+ and Docker Compose.
2. Copy `.env.example` to `.env`.
3. Set a real Telegram bot token and a random session secret of at least 32 characters in local environment or deployment secret storage.
4. Start database services: `docker compose up -d postgres redis`.
5. Install Python dependencies: `python -m pip install -r requirements.txt`.
6. Apply database migrations: `alembic upgrade head`.
7. Run unit tests: `python -m pytest`.
8. Run the API locally: `uvicorn app.main:app --reload`.

The current Compose API service expects a local `.env` file. Never commit it.

## Implemented scaffold

- FastAPI liveness endpoint.
- Telegram Mini App `initData` signature and age verification, user persistence, initial point-balance creation, and signed bearer sessions.
- Authenticated `GET /api/v1/me` endpoint that returns the active user's profile and points balance.
- Farming API: `GET /api/v1/farming`, `POST /api/v1/farming/start`, and `POST /api/v1/farming/{session_id}/claim`. Reward rate is server-controlled.
- Task API: list active tasks, submit a task, and view the current user's submissions.
- Referral attribution endpoint for authenticated users, plus owner/operator-only referral qualification with reward issuance and audit logging.
- Admin role dependency, task creation, pending/review queue, task-submission review, and `GET /api/v1/admin/me`.
- SQLAlchemy models and Alembic migrations for users, balances, ledger, farming sessions, tasks/submissions, referrals, admin users, and audit logs.
- Points, farming, task review, and referral service functions.
- Database-level partial unique index plus user-row locking to prevent multiple active farming sessions per user.
- Redis-backed rate limiting on Telegram login, farming, task submission, referral attribution, and admin reward/review mutations.
- Unit tests for selected authentication and service validation paths, plus a GitHub Actions test workflow.

## Important limitations

- Admin management and audit-log writing endpoints are not implemented; the current admin endpoint only verifies access and returns the admin identity.
- These routes are an initial API layer; integration coverage and operational safeguards still need to expand. Admin user provisioning/management and referral qualification policy are not fully implemented.
- Database concurrency, rollback, idempotency and ledger/balance consistency have **not yet been verified against PostgreSQL**.
- SQLite-backed database invariant tests cover ledger idempotency, conflicting idempotency keys, insufficient balance rollback, and the active-farming uniqueness index. These do not emulate PostgreSQL row locks; PostgreSQL concurrency tests are still required. CI status must be checked before treating a commit as validated.
- Server-side account status is checked on every authenticated request, so disabling a user or admin takes effect immediately. Token rotation/revocation lists, production secrets policy, backup/restore automation, frontend, and deployment hardening remain incomplete.
- No token distribution is implemented or promised. Points do not guarantee token allocation or monetary value.

## Railway deployment

The Railway `airdrop-engine` service should use the repository `Dockerfile`, set `DATABASE_URL` and `REDIS_URL` from the same Railway environment's Postgres and Redis services, and run `alembic upgrade head` before serving traffic. The `/health/live` endpoint is the deployment health check.

## Security principles

- Never commit `.env`, Telegram bot tokens, database credentials, signing keys, or production secrets.
- Validate Telegram Mini App `initData` server-side; never trust client-supplied identity.
- Calculate rewards server-side only.
- Use a single database transaction for ledger entries, balance projections, and reward state transitions.
- Use idempotency keys and concurrency controls for every reward operation.
- Verify all MVP security criteria and operational recovery procedures before beta.
