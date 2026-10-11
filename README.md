# Airdrop Engine

Telegram bot and Mini App backend for points farming, task campaigns, referrals, and future token-reward eligibility.

> **Development status:** early scaffold. Do not deploy to production or open public farming yet.

## Stack
- Python 3.12, FastAPI, aiogram 3
- PostgreSQL, SQLAlchemy 2, Alembic
- Redis (configured for future rate limits and background jobs)
- Next.js + TypeScript (planned for Mini App and admin UI)
- pytest and GitHub Actions CI

## Local setup

1. Install Python 3.12+ and Docker Compose.
2. Copy `.env.example` to `.env`.
3. Set a real Telegram bot token only in local environment or deployment secret storage.
4. Start database services: `docker compose up -d postgres redis`.
5. Install Python dependencies: `python -m pip install -r requirements.txt`.
6. Apply the initial database migration: `alembic upgrade head`.
7. Run the current unit tests: `python -m pytest`.
8. Run the API locally: `uvicorn app.main:app --reload`.

The current Compose API service expects a local `.env` file. Never commit it.

## Implemented scaffold

- FastAPI liveness endpoint and initial Telegram Mini App `initData` signature/age verification.
- SQLAlchemy models and an initial Alembic migration for users, balances, ledger, farming sessions, tasks, and task submissions.
- Initial points, farming, and task review service functions.
- Unit tests for selected authentication and service validation paths.
- GitHub Actions workflow for Python unit tests.

## Important limitations

- Authentication currently verifies Telegram `initData` but **does not issue a user session** or persist/login users through the API.
- Points/farming/task service functions are not yet wired into API routes.
- Database concurrency, rollback, idempotency and ledger/balance consistency have **not yet been verified against PostgreSQL**.
- The current service-level tests are not a substitute for integration tests with a real database.
- Referral attribution, admin RBAC, audit logging, distributed rate limiting, production secrets policy, backup/restore automation, frontend, and deployment hardening remain incomplete.
- No token distribution is implemented or promised. Points do not guarantee token allocation or monetary value.

## Security principles

- Never commit `.env`, Telegram bot tokens, database credentials, signing keys, or production secrets.
- Validate Telegram Mini App `initData` server-side; never trust client-supplied identity.
- Calculate rewards server-side only.
- Use a single database transaction for ledger entries, balance projections, and reward state transitions.
- Use idempotency keys and concurrency controls for every reward operation.
- Verify all MVP security criteria and operational recovery procedures before beta.
