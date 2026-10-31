# FarmTrack API

FarmTrack API is the FastAPI backend for the FarmTrack poultry farm management app. It provides the versioned REST API used by the separately maintained mobile/web client and persists farm, stock, sales, purchasing and accounting records in PostgreSQL.

## Features

- Authentication, refreshable sessions and device/session security controls.
- Multiple users per farm with owner, manager and worker roles.
- Farm settings, contacts, products, units, blocks and chicken batches.
- Chicken purchases, receipts, sales, deliveries, returns, refunds and settlements.
- Egg collections, losses and sales.
- Inventory purchases, movements, consumption and expenses.
- Reminders, notifications and farm activity history.
- Sales reports and accrual profitability reporting with stock-cost tracking.

## Requirements

- Python 3.12 recommended.
- PostgreSQL database.
- A supported Python package installer (`pip`).

The application uses PostgreSQL-specific database behavior and the async `asyncpg` driver. A generic SQLite database is not a supported substitute.

## Local development

From the backend repository root, create and activate a virtual environment, then install the development dependencies:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env
```

On Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Edit `.env` with the PostgreSQL connection string and a unique JWT signing key before starting the API. The signing key must be at least 32 characters. Generate one locally with:

```sh
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Do not use the example placeholder as a production key. Never commit `.env` or expose signing keys in logs, screenshots or client builds.

### Database migrations

Create the configured PostgreSQL database, set `DATABASE_URL`, then apply migrations:

```sh
alembic upgrade head
```

To see the current migration revision:

```sh
alembic current
```

Apply migrations before starting a new deployment. Back up production data and review generated migrations before applying them to a live database.

### Run the API

```sh
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API is served under `/api/v1`. When running locally, the interactive OpenAPI documentation is available at `http://localhost:8000/docs` and the ReDoc view at `http://localhost:8000/redoc`.

Set `CORS_ORIGINS` to a comma-separated list of trusted browser origins when serving the web client. Native applications do not use browser CORS enforcement. Do not use unrestricted origins with credentials in production.

## Configuration

Settings are loaded from environment variables or a local `.env` file. Names are case-insensitive.

| Variable | Required | Description |
| --- | --- | --- |
| `DATABASE_URL` | Yes | PostgreSQL SQLAlchemy async URL, e.g. `postgresql+asyncpg://user:password@localhost:5432/farmtrack`. |
| `JWT_SECRET_KEY` | Yes | Private JWT signing key; at least 32 characters. |
| `ENVIRONMENT` | No | `development`, `testing` or `production`; defaults to `development`. |
| `DEBUG` | No | FastAPI debug mode; defaults to `false`. Keep disabled in production. |
| `TIMEZONE` | No | Application default timezone; defaults to `Africa/Nairobi`. |
| `CORS_ORIGINS` | No | Comma-separated allowed browser origins; defaults to none. |
| `MEDIA_DIRECTORY` | No | Local farm-logo upload directory; defaults to `backend/media`. |
| `LOG_LEVEL` | No | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`; defaults to `INFO`. |
| `LOG_DIR` | No | Runtime log directory; defaults to `logs`. |
| `DATABASE_POOL_SIZE` | No | Database connection pool size; defaults to `5`. |
| `DATABASE_MAX_OVERFLOW` | No | Additional overflow connections; defaults to `5`. |
| `DATABASE_POOL_TIMEOUT` | No | Connection acquisition timeout in seconds; defaults to `30`. |
| `DATABASE_POOL_RECYCLE` | No | Connection recycle interval in seconds; defaults to `1800`. |
| `DATABASE_POOL_PRE_PING` | No | Validate pooled connections before use; defaults to `true`. |
| `DATABASE_ECHO` | No | SQLAlchemy SQL logging; defaults to `false`. |
| `JWT_ALGORITHM` | No | Only `HS256` is supported; defaults to `HS256`. |
| `JWT_ISSUER` | No | Token issuer; defaults to `farmtrack`. |
| `JWT_AUDIENCE` | No | Token audience; defaults to `farmtrack-mobile`. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | Access token lifetime; defaults to `15`. |
| `REFRESH_TOKEN_EXPIRE_DAYS` | No | Refresh token lifetime; defaults to `30`. |

The full settings model and validation rules are in `app/core/config.py`.

### Connection budget for multiple API instances

SQLAlchemy creates a connection pool per API process. Budget for the maximum
number of possible application connections with:

```text
API instances × processes per instance × (DATABASE_POOL_SIZE + DATABASE_MAX_OVERFLOW)
```

Add connections used by migrations, monitoring, admin tools, and background
workers, and leave capacity below PostgreSQL's `max_connections` for maintenance
and failover. The defaults allow up to 10 connections per process. The API logs
that per-process ceiling at startup; compare it with your deployment's instance
and worker count before scaling out. Monitor active/idle PostgreSQL connections,
pool wait timeouts, and query latency. Reduce per-process pool limits or use a
PostgreSQL connection pooler when the calculated budget approaches the database
limit.

## Tests

Run the complete backend test suite:

```sh
python -m pytest
```

Run a focused test module:

```sh
python -m pytest tests/test_profitability_report_service.py -q
```

The test dependencies are kept separate from runtime dependencies in `requirements-dev.txt`.

## Project structure

- `app/api/v1/endpoints/` — API route handlers.
- `app/schemas/` — request and response validation models.
- `app/services/` — business rules and workflows.
- `app/repositories/` — database query and persistence operations.
- `app/models/` — SQLAlchemy ORM models.
- `app/core/` — settings, database, security, errors and logging.
- `alembic/versions/` — versioned schema migrations.
- `tests/` — service, repository and API behavior tests.
- [`docs/database-schema.md`](docs/database-schema.md) — reference diagram and description of the current ORM schema.

The schema document describes the models registered in the source tree; it is not a live database dump.

Farm access is managed through `farm_memberships`. Owners can invite managers or
workers; managers can invite and manage workers; workers can use farm
operations but cannot edit farm settings, manage members, or delete the farm.
Invitations are currently for existing active FarmTrack accounts and are
accepted in-app through `GET /api/v1/farms/invitations` and
`POST /api/v1/farms/invitations/{membership_id}/accept`. An email delivery
integration is not included yet.

## Companion client

FarmTrack Mobile is maintained as a separate repository. Configure its `EXPO_PUBLIC_API_URL` with this API's origin (without `/api/v1`); the client appends the versioned API path itself.

## Security

Do not commit `.env`, credentials, production database URLs, user-uploaded media, or runtime logs. Use a strong unique signing key per environment and restrict production CORS origins. Report security issues privately to the repository maintainers rather than publishing credentials or exploitable details in an issue.

## License

FarmTrack does not currently specify a project license. You can push the repository without selecting one. If published without a license, the default copyright applies and no additional permissions to reuse, modify or distribute FarmTrack are granted.
