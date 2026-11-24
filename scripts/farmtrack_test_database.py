from __future__ import annotations

import argparse
import ipaddress
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import MutableMapping, TextIO
from urllib.parse import unquote, urlsplit


_DATABASE_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_]*_test\Z")


class TestDatabaseConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class TestDatabaseTarget:
    host: str
    database: str


def validate_test_database_url(url: str | None) -> TestDatabaseTarget:
    if not url or url != url.strip() or any(character.isspace() for character in url):
        raise TestDatabaseConfigurationError(
            "FARMTRACK_TEST_DATABASE_URL must be set to a valid local test URL."
        )

    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
        database = unquote(parsed.path[1:], errors="strict")
    except (UnicodeDecodeError, ValueError):
        raise TestDatabaseConfigurationError(
            "FARMTRACK_TEST_DATABASE_URL has invalid URL syntax."
        ) from None

    if parsed.scheme != "postgresql+asyncpg":
        raise TestDatabaseConfigurationError(
            "FARMTRACK_TEST_DATABASE_URL must use postgresql+asyncpg."
        )
    if not host or parsed.query or parsed.fragment:
        raise TestDatabaseConfigurationError(
            "The test URL must have a host and database, with no query or fragment."
        )
    if parsed.path.count("/") != 1 or not database:
        raise TestDatabaseConfigurationError(
            "The test URL must identify exactly one database."
        )
    if port is not None and not 1 <= port <= 65535:
        raise TestDatabaseConfigurationError(
            "FARMTRACK_TEST_DATABASE_URL has an invalid port."
        )

    normalized_host = host.lower()
    if normalized_host != "localhost":
        try:
            is_loopback = ipaddress.ip_address(normalized_host).is_loopback
        except ValueError:
            is_loopback = False
        if not is_loopback:
            raise TestDatabaseConfigurationError(
                "The PostgreSQL test host must be localhost or a loopback address."
            )

    if not _DATABASE_NAME_PATTERN.fullmatch(database):
        raise TestDatabaseConfigurationError(
            "The test database name must match <name>_test using letters, digits, "
            "and underscores."
        )

    return TestDatabaseTarget(host=normalized_host, database=database)


def configure_test_database(
    environ: MutableMapping[str, str] | None = None,
) -> TestDatabaseTarget:
    environment = os.environ if environ is None else environ
    test_url = environment.get("FARMTRACK_TEST_DATABASE_URL")
    target = validate_test_database_url(test_url)

    configured_url = environment.get("DATABASE_URL")
    if configured_url and configured_url != test_url:
        raise TestDatabaseConfigurationError(
            "DATABASE_URL is already set to a different URL; refusing to override it."
        )

    configured_environment = environment.get("ENVIRONMENT", "").strip().lower()
    if configured_environment == "production":
        raise TestDatabaseConfigurationError(
            "Tests cannot run when ENVIRONMENT is set to production."
        )

    environment["DATABASE_URL"] = test_url
    environment["ENVIRONMENT"] = "testing"
    return target


def announce_test_database(target: TestDatabaseTarget, stream: TextIO = sys.stdout) -> None:
    print(
        "Validated PostgreSQL test target: "
        f"host={target.host} database={target.database}",
        file=stream,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Safely prepare the explicitly configured FarmTrack test database."
    )
    parser.add_argument(
        "command",
        choices=("upgrade",),
        help="Apply the project's Alembic migrations to the validated test database.",
    )
    args = parser.parse_args(argv)

    try:
        target = configure_test_database()
    except TestDatabaseConfigurationError as error:
        print(f"Test database safety check failed: {error}", file=sys.stderr)
        return 2

    announce_test_database(target)
    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))

    try:
        from alembic import command
        from alembic.config import Config

        alembic_config = Config(str(project_root / "alembic.ini"))
        command.upgrade(alembic_config, "head")
    except Exception as error:
        print(
            "Alembic upgrade failed "
            f"({type(error).__name__}); connection details were suppressed.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
