# Staging and production deployment

This repository has a staging Compose profile, but **no environment is deployed by this file alone**. A server, DNS, TLS termination, and real deployment secrets must be supplied by the operator.

## Prerequisites

- A dedicated Linux host or staging VM with Docker Engine and Docker Compose v2.
- A domain name and TLS reverse proxy (Caddy, Traefik, or managed ingress) forwarding to the API service on the private Docker network.
- A Telegram bot token for the staging bot (do not reuse the production bot).
- A randomly generated session secret of at least 32 characters.
- Firewall rules that expose only SSH and HTTPS; do not expose PostgreSQL or Redis publicly.
- Persistent storage and an off-host backup destination.

## Configure staging

Create an untracked `.env.staging` on the server. Never commit this file or paste its values into issues/logs.

```dotenv
POSTGRES_DB=airdrop_engine_staging
POSTGRES_USER=airdrop
POSTGRES_PASSWORD=<unique-long-random-password>
TELEGRAM_BOT_TOKEN=<staging-bot-token>
SESSION_SECRET=<at-least-32-random-characters>
TELEGRAM_INITDATA_MAX_AGE_SECONDS=300
```

Use a password without URL-reserved characters in the current connection-string interpolation, or URL-encode it before using it in `DATABASE_URL`. For production, prefer managed secret injection and a separately provisioned least-privilege database role.

## First staging deployment

From the repository directory on the host:

```bash
docker compose --env-file .env.staging -f docker-compose.staging.yml build
docker compose --env-file .env.staging -f docker-compose.staging.yml up -d postgres redis
docker compose --env-file .env.staging -f docker-compose.staging.yml run --rm migrate
docker compose --env-file .env.staging -f docker-compose.staging.yml up -d api
docker compose --env-file .env.staging -f docker-compose.staging.yml ps
```

Verify the API liveness endpoint through the private host or TLS proxy: `GET /health/live`. Then test Telegram login with the staging bot, farming start/claim, task submission/review, referral qualification, rate limiting, and database persistence. Do not open public beta until these flows pass.

## Upgrade and rollback

1. Back up PostgreSQL and verify the backup can be restored to a separate database.
2. Build and deploy the exact commit SHA; do not deploy an unpinned `latest` tag.
3. Review Alembic changes before applying them. Run migrations once, before replacing API containers.
4. Verify `/health/live`, authentication, reward ledger invariants, logs, and error rates.
5. If application health fails, roll back to the previous image/commit only if the schema migration is backward-compatible. Database migrations are not automatically reversed.

## Production gates

- [ ] HTTPS, DNS, firewall, and trusted-proxy configuration verified.
- [ ] Production Telegram bot and secrets stored in a secret manager.
- [ ] PostgreSQL backups scheduled and restore drill passed.
- [ ] Redis persistence/availability and capacity decisions documented.
- [ ] Logs, metrics, alerts, disk capacity, and restart behavior verified.
- [ ] PostgreSQL concurrency tests and end-to-end tests pass against the target configuration.
- [ ] Admin provisioning and recovery procedure tested.
- [ ] Abuse controls and per-account rate limits reviewed.
- [ ] Privacy policy, terms, support/contact path, and points/reward terms published.
- [ ] Explicit launch approval obtained.

The current API is an early scaffold. Staging deployment is for validation only, not a signal that the service is production-ready.
