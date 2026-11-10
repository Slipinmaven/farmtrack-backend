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
- Searchable, paginated sale and purchase receipt history, including each recorded payment.
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
| `SMTP_HOST` | No | SMTP server hostname; defaults to Gmail's `smtp.gmail.com`. |
| `SMTP_PORT` | No | SMTP port; defaults to `587` (STARTTLS). |
| `SMTP_USERNAME` | No | Gmail account address used to authenticate. |
| `SMTP_PASSWORD` | No | Google app password for that account. Keep it in the server environment and never expose it to the mobile app. |
| `SMTP_FROM_EMAIL` | No | Sender address; defaults to `SMTP_USERNAME`. For Gmail, use the same address unless you have configured a Gmail send-as alias. |
| `FARMTRACK_APP_URL` | No | App link included in farm invitation emails; defaults to `farmtrack://farm-team`. |
| `APP_RELEASE_ADMIN_EMAILS` | No | Comma-separated FarmTrack accounts authorized to register Android releases and email download invitations. |
| `GITHUB_RELEASE_REPOSITORY` | For APK distribution | Private GitHub repository in `owner/repository` format. |
| `GITHUB_RELEASE_TOKEN` | For APK distribution | Server-only fine-grained token with Contents read-only access to the release repository. Never put it in the mobile app or expose it in logs/responses. |
| `APP_PUBLIC_BASE_URL` | No | Public HTTPS origin of this backend, used to create download links. |
| `DOWNLOAD_TOKEN_EXPIRY_DAYS` | No | Download invitation lifetime; defaults to 7 days. |

The full settings model and validation rules are in `app/core/config.py`.

Farm invitation emails are added to the transactional outbox and sent by the
background worker, with retries. Configure both `SMTP_USERNAME` and
`SMTP_PASSWORD` to enable delivery. If they are absent,
invitations still work in-app and the membership response reports
`invitation_email_status: "not_configured"`. Delivery status is visible in the
farm team list; failed deliveries can be retried from the app. Never send or
log the initial password set by an owner; users must receive it through a
separate secure channel.

For Gmail SMTP, enable 2-Step Verification on the Google account, create an
app password for FarmTrack, and place the 16-character app password in the
backend `.env` as `SMTP_PASSWORD` (without the display spaces). Do not use the
account's regular Google password. Set `SMTP_USERNAME` to the Gmail account
address. Optionally set `SMTP_FROM_EMAIL`; otherwise the account address is
used as the sender. Keep these values only on the backend server.

To send a real test email through Gmail SMTP (without using the database or
creating a farm invitation), run this from the backend directory after setting
the SMTP values in `.env`:

```powershell
python scripts/send_test_email.py you@example.com
```

Replace the address with an inbox you control. The command sends an actual
email.

### Android app download distribution

APK distribution uses a private GitHub repository for release assets. Configure
`GITHUB_RELEASE_REPOSITORY` as `owner/repository` and set
`GITHUB_RELEASE_TOKEN` to a fine-grained personal access token limited to that
repository with **Contents: read-only** permission. Keep the token only in the
backend host's environment; it must never be included in the mobile app. Set
`APP_PUBLIC_BASE_URL` to the public HTTPS backend origin and
`APP_RELEASE_ADMIN_EMAILS` to a comma-separated allowlist of administrator
account emails.

Release administrators can search active registered users, select multiple
recipients, and invite by email, WhatsApp, or both. Email is sent by the
configured SMTP service. WhatsApp invitations use a prepared click-to-send
message for a linked farm phone number; the administrator must review and send
the message in WhatsApp. Farm phone numbers need an international country code.
Apply the latest Alembic migration before using these recipient and WhatsApp
features.

To publish a mobile build, increment `expo.version` in `app.json` in the
separate mobile repository, then run this command from that repository:

```sh
eas build --profile production --platform android
```

The production EAS profile creates an APK and automatically increments the
Android version code using EAS's remote version source. Download the build
artifact and attach it to a published GitHub Release in the configured private
repository. Use GitHub CLI, while authenticated to that repository, to find the
uploaded asset ID:

```sh
gh api repos/OWNER/REPOSITORY/releases/tags/v1.2.3 --jq '.assets[] | {id, name, size}'
```

An allowlisted administrator then registers it with `POST /api/v1/app-releases`:

```json
{
  "version": "1.2.3",
  "version_code": 123,
  "platform": "android",
  "github_asset_id": 123456,
  "release_notes": "Bug fixes and improvements.",
  "is_latest": true
}
```

The backend verifies the asset in the configured repository and takes the APK
filename and size from GitHub's metadata. An administrator can list releases with
`GET /api/v1/app-releases`, and send an invitation with
`POST /api/v1/app-releases/{release_id}/invitations`. Release management
requires an authenticated FarmTrack account. The email link itself does not
require an account: `GET /api/v1/downloads/{token}` validates a time-limited
invitation credential and obtains a temporary GitHub asset URL using the
server-only token. GitHub serves the APK directly where possible; otherwise
the backend streams it without buffering the whole file.
An administrator can revoke a previously issued link with
`DELETE /api/v1/app-releases/invitations/{invitation_id}`.
Download tokens are stored hashed and expire after the configured number of
days. Apply the Alembic migrations before using these endpoints. Existing
Supabase-backed release records are preserved but deactivated by the migration;
register their GitHub assets as new releases.

Send an invitation with `{"recipient_email":"person@example.com"}`. The
backend responds only after SMTP accepts the email and does not return the raw
download token. If sending fails, the token is marked failed and revoked.

For a Render free-tier service, the first link request may wait for the API to
wake from sleep. When GitHub returns a temporary asset URL, GitHub serves the
APK directly; if GitHub streams the asset response instead, the backend proxies
the APK as a stream.

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
workers and create accounts for new users; managers can invite and manage
workers; workers can use farm operations but cannot edit farm settings, manage
members, or delete the farm. New accounts require an owner-provided initial
password of at least 8 characters. The password is not emailed; the owner must
share it with the user through a secure channel. Users accept their farm
invitations in-app through `GET /api/v1/farms/invitations` and
`POST /api/v1/farms/invitations/{membership_id}/accept`. Farm invitation email
delivery uses Gmail SMTP when configured; account passwords are never included
in email. A forced initial-password change is not included yet.

## Companion client

FarmTrack Mobile is maintained as a separate repository. Configure its `EXPO_PUBLIC_API_URL` with this API's origin (without `/api/v1`); the client appends the versioned API path itself.

## Security

Do not commit `.env`, credentials, production database URLs, user-uploaded media, or runtime logs. Use a strong unique signing key per environment and restrict production CORS origins. Report security issues privately to the repository maintainers rather than publishing credentials or exploitable details in an issue.

## License

FarmTrack does not currently specify a project license. You can push the repository without selecting one. If published without a license, the default copyright applies and no additional permissions to reuse, modify or distribute FarmTrack are granted.
