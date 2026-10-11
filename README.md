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
- Admin role dependency and read-only `GET /api/v1/admin/me` endpoint for active admins with supported roles.
- SQLAlchemy models and Alembic migrations for users, balances, ledger, farming sessions, tasks/submissions, referrals, admin users, and audit logs.
- Points, farming, task review, and referral service functions.
- Database-level partial unique index plus user-row locking to prevent multiple active farming sessions per user.
- Redis-backed rate limiting on Telegram login.
- Unit tests for selected authentication and service validation paths, plus a GitHub Actions test workflow.

## Important limitations

- Admin management and audit-log writing endpoints are not implemented; the current admin endpoint only verifies access and returns the admin identity.
- Points/farming/task/referral service functions are not yet wired into public API routes.
- Database concurrency, rollback, idempotency and ledger/balance consistency have **not yet been verified against PostgreSQL**.
- Service-level tests are not a substitute for integration tests with a real database. CI status must be checked before treating a commit as validated.
- Session revocation/rotation, comprehensive admin audit enforcement, production secrets policy, backup/restore automation, frontend, and deployment hardening remain incomplete.
- No token distribution is implemented or promised. Points do not guarantee token allocation or monetary value.

## Security principles

- Never commit `.env`, Telegram bot tokens, database credentials, signing keys, or production secrets.
- Validate Telegram Mini App `initData` server-side; never trust client-supplied identity.
- Calculate rewards server-side only.
- Use a single database transaction for ledger entries, balance projections, and reward state transitions.
- Use idempotency keys and concurrency controls for every reward operation.
- Verify all MVP security criteria and operational recovery procedures before beta.
