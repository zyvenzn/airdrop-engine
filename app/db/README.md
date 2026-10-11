# Database status

Initial SQLAlchemy models exist for users, point balance projections, and an append-only points ledger.

Important limitations:
- Migrations are not yet configured or generated.
- The API does not yet write to these tables.
- The ledger/balance transactional service and concurrency tests are not yet implemented.
- Do not treat this schema scaffold as proof that balance consistency is verified.

Before beta, add Alembic migrations, transactional reward services, idempotency/replay handling, and integration tests against PostgreSQL.
