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
- A farm-scoped, read-only AI assistant with provider failover and controlled farm-data tools.

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

### Read-only AI assistant

The assistant endpoint is read-only and scoped to the authorized farm. The
general `/assistant/chat` endpoint can answer ordinary conversation without
fetching data, and can call registered tools for current contact balances,
contact ledger history, inventory balances, and explicitly requested
profitability reports, and date-bounded poultry/egg operations summaries
(collections, losses, chicken movements, and product consumption). Operations
summaries can optionally be filtered by an exact block name. It can also read
sales and pending outgoing deliveries, report current chicken occupancy by
block, and provide allowlisted links to relevant app screens. Relative periods
use the farm's configured timezone and the assistant receives the current local
date and time. Sales questions can resolve rolling periods such as the previous
hour and clock-hour questions such as "at 1pm today" against each sale's
recorded transaction time. Transactions without a recorded time are excluded
from time-of-day matches. Omitted periods use each tool's documented default.
Egg losses are not block-attributed
in the underlying records, so block summaries explicitly exclude farm-wide egg
losses. Product rankings are withheld when the sales report's 100-transaction
limit truncates the matching period. The assistant can also search paginated
purchase and sales histories, then trace a selected transaction through its
payments, settlements, applicable returns/refunds, and replacements. It can
include chicken purchase receipts and sale deliveries when recorded. Expense
tools provide category totals or paginated entries; the profitability report
remains the source for net-profit questions. Product records describe the farm's
catalog, while shared units and each product's configured conversions describe
how quantities are measured; expense categories classify costs and are not
unit categories. Incoming supplier arrival data outside recorded chicken
receipts and evidence-based sale-price recommendations are not available as
assistant data. The assistant does not have arbitrary database or API access.
Contact tool results exclude contact IDs, email, phone, address, references,
and notes. The mobile app uses the same endpoint regardless of the active AI
provider.

Navigation requests may include an optional `source_route` containing the
internal screen path from which FarmMate was opened. It is used only to tailor
navigation guidance, not to authorize farm data. Chicken workflow guidance
covers purchase, sale, loss, and movement entry points and form requirements.
Purchase arrivals and chicken-sale deliveries are described as separate actions
after their respective records. Egg workflow guidance covers the Eggs tab's
conditional actions, verified collection, sale, and loss entry points, and
form review/confirmation steps. Egg losses are deducted from combined farm
stock rather than attributed to a block. The chat response can include
structured `suggested_replies` for optional follow-up guidance; these submit a
normal chat question and do not enter or save transaction data.

Configure any desired server-side provider keys. The manager tries configured
providers in this order: Groq, Gemini, then OpenRouter. Groq and OpenRouter use
OpenAI-compatible chat completions; all providers share the same FarmTrack
tool executor, authorization boundaries, and sanitized results. A failed
read-only provider attempt can be retried through the next configured provider.
Tool results are cached for the duration of a request so a failover does not
repeat a completed read. Each provider is attempted at most once per request.
The default Groq model is `qwen/qwen3.8-27b`; the default OpenRouter model is
`openrouter/free`. OpenRouter selects an available free model and filters for
requested capabilities such as tool calling. Free model availability and
provider rate limits can change; the selected model may vary between requests.

429 responses use provider reset/retry headers when available, or quota
metadata to distinguish a daily quota from a short rate limit; otherwise a
short 60-second cooldown is used. A 404 (for example, an unavailable model or
endpoint) also triggers failover and a five-minute cooldown for that provider.
500/502/503 failures and timeouts cause bounded cooldowns. Invalid requests
(400) and authentication/permission errors (401/403) do not trigger failover
within that request. Cooldown and health state is in memory per API process;
it resets on restart and is not shared between multiple workers or replicas.
If all providers are unavailable, the same API endpoint returns a friendly
temporary-unavailable response.

Never put provider keys in the mobile/web client or commit them to `.env`.
Provider usage limits still apply; failover cannot provide unlimited free
usage. The chat endpoint is
`POST /api/v1/farms/{farm_id}/assistant/chat`. The legacy profitability
endpoint remains available for compatibility.

```http
POST /api/v1/farms/{farm_id}/assistant/chat
Authorization: Bearer <access-token>
Content-Type: application/json

{
  "question": "How much feed do I have in stock?",
  "source_route": "/(tabs)/flock"
}
```

The caller must have access to the farm. Requests are limited to 2,000
characters and a 367-day report period. Provider output is capped, and upstream
error details are not returned. A successful response includes a
`conversation_id`; send it in later chat requests to append messages. History
can be listed with
`GET /api/v1/farms/{farm_id}/assistant/conversations?limit=50&offset=0`,
retrieved with
`GET /api/v1/farms/{farm_id}/assistant/conversations/{conversation_id}`, and
deleted with
`DELETE /api/v1/farms/{farm_id}/assistant/conversations/{conversation_id}`.
Users can only list, retrieve, or delete their own conversations in that farm.
Email addresses and phone numbers in questions are rejected, and responses are
not cached. Apply database migrations before using persistent history.
Configure quotas and billing limits with each selected provider before enabling
the endpoint for general use.

### Run the API

```sh
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API is served under `/api/v1`. When running locally, the interactive OpenAPI documentation is available at `http://localhost:8000/docs` and the ReDoc view at `http://localhost:8000/redoc`.

Set `CORS_ORIGINS` to a comma-separated list of trusted browser origins when serving the web client. Native applications do not use browser CORS enforcement. Do not use unrestricted origins with credentials in production.

## Configuration

Settings are loaded from environment variables or a local `.env` file. Names are case-insensitive.

Accounts have a global `USER` or `SUPER_ADMIN` role, separate from farm
membership roles. The role migration promotes the configured initial
super-admin account if it exists. Apply migrations with `alembic upgrade head`
before deploying the matching API and mobile versions, then verify the
intended account's role in the database. Only `SUPER_ADMIN` accounts can use
FarmMate's tool-enabled assistant routes; other users see a testing notice and
cannot call those routes.

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
| `EMAIL_GATEWAY_URL` | For email delivery | HTTPS URL of the deployed Google Apps Script email gateway. |
| `EMAIL_GATEWAY_SECRET` | For email delivery | Shared gateway secret sent only from the backend. Keep it in the server environment and never expose it to the mobile app. |
| `EMAIL_GATEWAY_TIMEOUT_SECONDS` | No | HTTP request timeout; defaults to `15` seconds. |
| `FARMTRACK_APP_URL` | No | Destination of the invitation email’s “Open FarmTrack” link; defaults to `farmtrack://farm-team`, which opens the Team & invitations route in a built app using the registered `farmtrack` scheme. This is a deep link, not a public website URL; recipients need the app installed. For Expo Go or browser testing, configure a URL reachable from the recipient’s device. Do not use `localhost` in emails sent to other devices. |
| `APP_RELEASE_ADMIN_EMAILS` | No | Comma-separated FarmTrack accounts authorized to register Android releases and email download invitations. |
| `GITHUB_RELEASE_REPOSITORY` | For APK distribution | Private GitHub repository in `owner/repository` format. |
| `GITHUB_RELEASE_TOKEN` | For APK distribution | Server-only fine-grained token with Contents read-only access to the release repository. Never put it in the mobile app or expose it in logs/responses. |
| `APP_PUBLIC_BASE_URL` | For APK distribution | Public HTTPS origin of this backend, used to create download links. |
| `DOWNLOAD_TOKEN_EXPIRY_DAYS` | No | Download invitation lifetime; defaults to 7 days. |
| `GROQ_API_KEY` | For Groq | Server-only Groq API key. First provider in the failover order when configured. |
| `GROQ_MODEL` | No | Groq chat model; defaults to `qwen/qwen3.8-27b`. |
| `GEMINI_API_KEY` | For Gemini | Server-only Google AI Studio API key. Second provider in the failover order when configured. |
| `GEMINI_MODEL` | No | Gemini model; defaults to `gemini-3-flash-preview`. |
| `OPENROUTER_API_KEY` | For OpenRouter | Server-only OpenRouter API key. Third provider in the failover order when configured. |
| `OPENROUTER_MODEL` | No | OpenRouter model; defaults to `openrouter/free`, which selects from available free models supporting requested features. |

The full settings model and validation rules are in `app/core/config.py`.

Farm invitation emails are added to the transactional outbox and sent by the
background worker, with retries. The backend uses one managed asynchronous
HTTP client to call the Google Apps Script gateway. Configure both
`EMAIL_GATEWAY_URL` and `EMAIL_GATEWAY_SECRET` to enable delivery. If either is
absent, invitations still work in-app and the membership response reports
`invitation_email_status: "not_configured"`. Delivery status is visible in the
farm team list; failed deliveries can be retried from the app. Never send or
log the initial password set by an owner; users must receive it through a
separate secure channel.

Set `EMAIL_GATEWAY_URL` to the deployed Apps Script web app URL and
`EMAIL_GATEWAY_SECRET` to the matching secret configured by that gateway.
Use HTTPS outside localhost. Keep both values on the backend server. The
gateway receives the recipient, subject, plain-text body and (when present)
styled HTML body; provider response details and email contents are not logged.

Account deletion requires the user's password and immediately starts a
30-day recovery period; a public base URL is not needed. The email gateway
sends a notification with the scheduled deletion date and instructions for
cancelling the request and securing the account if the user did not make it.
Users keep access during the recovery period and can cancel in Account & access.
Email delivery is best-effort and does not undo a scheduled deletion if the
gateway is unavailable.

To send a real test email through the gateway (without using the database or
creating a farm invitation), run this from the backend directory after
configuring the gateway values in `.env`:

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
configured FarmTrack Email Gateway. A release can also be shared without a
recipient phone number using a private invitation link. Share links open a branded
landing page with Open Graph metadata and a preview image before the secure
download. WhatsApp messages include the release version, notes, and share
link; the generated download password is shown separately in Release Admin and
must be sent separately. Email invitations include both the private link and
its generated password. Administrators may also prepare messages for specific
phone numbers; phone numbers need an international country code. Apply the
latest Alembic migrations before using these recipient and WhatsApp features.

Signed-in Android apps can check `GET /api/v1/app-releases/updates/latest` with
the `current_version_code` query parameter and download a newer active release
through `GET /api/v1/app-releases/updates/{release_id}/download`. Both endpoints
require an authenticated FarmTrack account. The update download is streamed
through the backend so the app's bearer token is never forwarded to GitHub's
temporary asset URL. Android still requires the user to confirm installation
in the system package installer.

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
require an account: `GET /api/v1/downloads/{token}` displays a password form.
Submitting the generated password to the same URL verifies the time-limited
invitation and obtains a temporary GitHub asset URL using the server-only token.
GitHub serves the APK directly where possible; otherwise the backend streams it
without buffering the whole file.
An administrator can revoke a previously issued link with
`DELETE /api/v1/app-releases/invitations/{invitation_id}`.
Download tokens and password hashes are stored; generated passwords are only
returned when an invitation is created. Passwords expire with their invitation,
which expires after the configured number of days. Applying the password
migration revokes existing invitations because their passwords cannot be
recovered; issue fresh links after deployment. Apply the Alembic migrations
before using these endpoints. Existing
Supabase-backed release records are preserved but deactivated by the migration;
register their GitHub assets as new releases.

Send an invitation with `{"recipient_email":"person@example.com"}`. The
backend responds only after the email gateway accepts the email and does not
return the raw download token. If sending fails, the token is marked failed and
revoked.

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
delivery uses the FarmTrack Email Gateway when configured; account passwords are never included
in email. A forced initial-password change is not included yet.

## Companion client

FarmTrack Mobile is maintained as a separate repository. Configure its `EXPO_PUBLIC_API_URL` with this API's origin (without `/api/v1`); the client appends the versioned API path itself.

## Security

Do not commit `.env`, credentials, production database URLs, user-uploaded media, or runtime logs. Use a strong unique signing key per environment and restrict production CORS origins. Report security issues privately to the repository maintainers rather than publishing credentials or exploitable details in an issue.

## License

FarmTrack does not currently specify a project license. You can push the repository without selecting one. If published without a license, the default copyright applies and no additional permissions to reuse, modify or distribute FarmTrack are granted.
