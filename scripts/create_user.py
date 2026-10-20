import argparse
import asyncio
from getpass import getpass
from pathlib import Path
import sys
from uuid import UUID

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError

# Make direct execution from the backend root resolve the application package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import async_session_factory, dispose_database_engine
from app.core.unit_of_work import UnitOfWork
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_session_repository import UserSessionRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService, normalize_email


async def create_user(email: str, password: str) -> UUID:
    async with async_session_factory() as session:
        unit_of_work = UnitOfWork(session)
        try:
            auth_service = AuthService(
                user_repository=UserRepository(session),
                refresh_token_repository=RefreshTokenRepository(session),
                user_session_repository=UserSessionRepository(session),
                unit_of_work=unit_of_work,
            )
            user = await auth_service.create_user(email=email, password=password)
            return user.id
        except IntegrityError:
            raise ValueError("A user with that email already exists.") from None


async def _create_user_and_dispose(email: str, password: str) -> UUID:
    try:
        return await create_user(email, password)
    finally:
        await dispose_database_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a FarmTrack user.")
    parser.add_argument("email", help="Email address for the new user")
    args = parser.parse_args()

    try:
        email = str(TypeAdapter(EmailStr).validate_python(args.email))
    except ValidationError:
        parser.error("Enter a valid email address.")
    email = normalize_email(email)

    password = getpass("Password: ")
    confirmation = getpass("Confirm password: ")
    if not password:
        parser.error("Password cannot be empty.")
    if password != confirmation:
        parser.error("The passwords do not match.")

    try:
        user_id = asyncio.run(_create_user_and_dispose(email, password))
    except ValueError as exc:
        parser.error(str(exc))

    print(f"Created user {email} (id: {user_id}).")


if __name__ == "__main__":
    main()