from __future__ import annotations

from io import StringIO

import pytest

from scripts.farmtrack_test_database import (
    TestDatabaseConfigurationError as DatabaseConfigurationError,
    announce_test_database,
    configure_test_database,
    validate_test_database_url,
)


VALID_URL = (
    "postgresql+asyncpg://test_user:never-print-this@127.0.0.1:55432/"
    "farmtrack_integration_test"
)


@pytest.mark.parametrize(
    ("url", "message"),
    [
        (None, "must be set"),
        ("", "must be set"),
        ("postgresql://user:password@localhost/farmtrack_test", "must use"),
        ("sqlite+aiosqlite:///farmtrack_test", "must use"),
        (
            "postgresql+asyncpg://user:password@db.example.com/farmtrack_test",
            "loopback",
        ),
        (
            "postgresql+asyncpg://user:password@localhost/farmtrack",
            "database name",
        ),
        (
            "postgresql+asyncpg://user:password@localhost/farmtrack_test?ssl=true",
            "query or fragment",
        ),
        (
            "postgresql+asyncpg://user:password@localhost/farmtrack_test#fragment",
            "query or fragment",
        ),
        (
            "postgresql+asyncpg://user:password@localhost:bad/farmtrack_test",
            "invalid URL syntax",
        ),
        (
            "postgresql+asyncpg://user:password@localhost/farmtrack_test/extra",
            "exactly one database",
        ),
    ],
)
def test_rejects_unsafe_or_malformed_urls(url, message):
    with pytest.raises(DatabaseConfigurationError, match=message):
        validate_test_database_url(url)


def test_configuration_sets_application_url_only_from_explicit_test_url():
    environ = {
        "FARMTRACK_TEST_DATABASE_URL": VALID_URL,
        "ENVIRONMENT": "development",
    }

    target = configure_test_database(environ)

    assert target.host == "127.0.0.1"
    assert target.database == "farmtrack_integration_test"
    assert environ["DATABASE_URL"] == VALID_URL
    assert environ["ENVIRONMENT"] == "testing"


def test_configuration_refuses_to_override_a_different_database_url():
    environ = {
        "FARMTRACK_TEST_DATABASE_URL": VALID_URL,
        "DATABASE_URL": "postgresql+asyncpg://other@localhost/farmtrack_dev",
    }

    with pytest.raises(
        DatabaseConfigurationError,
        match="already set to a different URL",
    ):
        configure_test_database(environ)


def test_configuration_refuses_production_environment():
    environ = {
        "FARMTRACK_TEST_DATABASE_URL": VALID_URL,
        "ENVIRONMENT": "production",
    }

    with pytest.raises(
        DatabaseConfigurationError,
        match="cannot run when ENVIRONMENT is set to production",
    ):
        configure_test_database(environ)


def test_announcement_contains_only_validated_host_and_database():
    target = validate_test_database_url(VALID_URL)
    output = StringIO()

    announce_test_database(target, stream=output)

    assert output.getvalue() == (
        "Validated PostgreSQL test target: "
        "host=127.0.0.1 database=farmtrack_integration_test\n"
    )
    assert "test_user" not in output.getvalue()
    assert "never-print-this" not in output.getvalue()
    assert "55432" not in output.getvalue()
