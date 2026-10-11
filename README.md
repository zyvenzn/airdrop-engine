# Airdrop Engine

Telegram Mini App and bot for points farming, task campaigns, referrals, and future token-reward eligibility.

> **Development status:** initial scaffold only. MVP security criteria are not yet verified.

## Planned stack
- Python 3.12, FastAPI, aiogram 3
- PostgreSQL, SQLAlchemy 2, Alembic
- Redis for rate limits and background jobs
- Next.js + TypeScript for Mini App and admin UI
- pytest for unit and integration tests

## Security principles
- Never commit `.env`, Telegram bot tokens, database credentials, signing keys, or production secrets.
- Validate Telegram Mini App `initData` server-side; never trust client-supplied identity.
- Calculate rewards server-side only.
- Treat the points ledger as the source of truth and update balance projections transactionally.
- Make reward operations idempotent and safe under concurrent requests.
- Points do not promise token allocation or monetary value.

## Status
This repository is not yet a deployable application. Authentication, farming, tasks, referrals, admin RBAC, anti-abuse controls, backup/restore, and CI tests must be implemented and verified before beta.
