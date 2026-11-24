# FarmTrack PostgreSQL Integration Tests

These tests exercise selected FastAPI routes against a disposable PostgreSQL database using the real Alembic migration chain. They are intentionally separate from the existing fake-based unit tests.

## Requirements

- Python dependencies from `requirements-dev.txt` and `requirements.txt`.
- A locally installed PostgreSQL server or a dedicated PostgreSQL CI service. Docker is optional; the instructions below do not require it.
- The database host must be `localhost` or a loopback IP address.
- The database name must match `<name>_test`, using letters, digits, and underscores. Example: `farmtrack_integration_test`.
- The connection must use `postgresql+asyncpg`. URL query strings and fragments are not accepted.

No backend GitHub Actions workflow was present when this setup was added, so no workflow or CI service configuration was changed.

## Provision a disposable database

Create a new local database dedicated to these tests using your PostgreSQL administration tool. For example, in a local PostgreSQL administrative session:

```sql
CREATE ROLE farmtrack_test LOGIN PASSWORD 'replace-with-a-local-test-password';
CREATE DATABASE farmtrack_integration_test OWNER farmtrack_test;
```

These are create-only setup statements. Do not substitute a development, shared, Supabase, staging, or production database. The test runner does not create, truncate, or drop databases.

If PostgreSQL is not installed locally, provision a dedicated test service through your approved local or CI environment. Do not assume Docker is available.

## Configure PowerShell

From the backend directory, set the explicit test URL. Replace the placeholder password with a URL-encoded password for the local test role:

```powershell
$env:FARMTRACK_TEST_DATABASE_URL = 'postgresql+asyncpg://farmtrack_test:replace-with-url-encoded-password@127.0.0.1:5432/farmtrack_integration_test'
```

The safety guard validates this URL before importing application settings, creating the application engine, or importing Alembic. It rejects missing values, non-PostgreSQL drivers, non-loopback hosts, database names without the `_test` suffix, URL query strings/fragments, malformed URLs, `ENVIRONMENT=production`, and a conflicting `DATABASE_URL`. It then sets `DATABASE_URL` to the validated explicit URL and `ENVIRONMENT=testing` for that process. The guard prints only the validated host and database name; it never prints credentials or query values.

Do not set `FARMTRACK_TEST_DATABASE_URL` to a shared database just because its database name ends in `_test`. The host must also be local/loopback.

## Apply migrations

The test database must be migrated explicitly. The wrapper validates the test URL before importing or running Alembic:

```powershell
python scripts/farmtrack_test_database.py upgrade
```

This runs the project's current migration chain through `head`. Integration-test collection does not run migrations automatically. If the safety check fails, correct the test-only environment; do not bypass the guard or point the command at a non-test host.

## Run the tests

Run the database-free safety-guard unit tests without a PostgreSQL connection:

```powershell
python -m pytest tests/test_test_database_guard.py -q
```

With the explicit test URL configured and migrations applied, run only the new PostgreSQL integration tests:

```powershell
python -m pytest tests/integration -q
```

The integration test `conftest.py` performs the same fail-closed validation before importing application modules. If the explicit URL is absent or unsafe, collection stops before an application engine or migration can be created.

## Isolation and coverage

Each integration test gets an async PostgreSQL connection and an outer transaction. Request sessions join that transaction using SQLAlchemy's `join_transaction_mode="create_savepoint"`, so a route/service `commit()` releases its savepoint without committing the outer transaction. Teardown rolls back the outer transaction. The dedicated rollback test creates a contact through the real API/service, confirms it is visible in the test transaction, and uses a fresh session after rollback to assert that the row is gone. No shared-table truncation or database drop is used.

The test-only FastAPI app includes the actual v1 router and normal exception handlers but does not start production lifespan workers. It overrides only `get_database_session` and `get_current_user`; `get_owned_farm`, contact services, repositories, and SQL queries remain real. The tests verify Farm A can retrieve its own contact and receives the existing `RESOURCE_NOT_FOUND`/404 response when requesting Farm B's contact ID through Farm A's route.

This first batch proves the contacts detail-read path and the transaction rollback fixture. It does not cover contact updates/deletes, other resource families, real JWT/session validation, production deployment, or every API route. The farm-filter regression experiment (temporarily removing the repository predicate and rerunning the foreign-ID test) has not been run; perform it only against this disposable PostgreSQL database and restore the source immediately afterward.

## Controlled farm-filter regression check

This check is optional and has not been performed as part of this setup. Run it only after the disposable database has been migrated and the ordinary integration tests pass.

1. From the backend directory, confirm `FARMTRACK_TEST_DATABASE_URL` points to the local disposable database. Do not use a shared, development, Supabase, staging, or production database.
2. Save an exact copy of `app\repositories\contact_repository.py` outside the repository, record its SHA-256 hash, and capture its pre-experiment `git diff`. Do not use `git checkout` or `git restore`, which could discard unrelated worktree changes.
3. In `ContactRepository.get_by_id`, temporarily remove only the `Contact.farm_id == farm_id` predicate, leaving the contact-ID predicate intact.
4. Run this focused test:

   ```powershell
   python -m pytest tests/integration/test_contacts_farm_isolation.py::test_farm_owner_cannot_read_foreign_contact_by_id -q
   ```

5. Confirm the test fails at the expected authorization assertion (the foreign contact is returned instead of a 404). A connection, migration, or setup failure does not demonstrate regression detection.
6. Immediately restore the saved file byte-for-byte, even if the test is interrupted or fails unexpectedly. Recompute the SHA-256 hash and confirm it matches the recorded value; compare `git diff -- app\repositories\contact_repository.py` with the pre-experiment diff to ensure the experiment introduced no remaining change.

Until this controlled check is run successfully, the foreign-contact test's ability to detect removal of the farm predicate remains unverified.
