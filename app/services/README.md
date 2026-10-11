# Service layer

Points, farming, and task reward service functions are introduced as an initial implementation.

Call each mutating service inside a single database transaction, e.g. `with SessionLocal.begin() as db:`. Do not call them against autocommit sessions.

Current limitations:
- API routes do not yet expose these services.
- PostgreSQL integration tests for concurrency/idempotency are not yet implemented.
- User creation/authentication sessions and admin authorization are not implemented.
- Redis rate limiting and production migrations are not implemented.
- The in-memory service tests are not a substitute for real database tests.
