from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import AsyncIterator, Iterator
from uuid import UUID, uuid4

from scripts.farmtrack_test_database import (
    TestDatabaseConfigurationError,
    announce_test_database,
    configure_test_database,
)

try:
    _TEST_DATABASE_TARGET = configure_test_database()
except TestDatabaseConfigurationError as error:
    raise RuntimeError(str(error)) from None

announce_test_database(_TEST_DATABASE_TARGET)

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.api.v1.router import router as v1_router
from app.core.database import get_database_session
from app.core.exception_handlers import register_exception_handlers
from app.dependencies.auth import get_current_user
from app.models.contact import Contact
from app.models.contact_roles import ContactRole
from app.models.farm import Farm
from app.models.user import User
from app.schemas.enums import ContactRoleEnum


@dataclass
class RollbackProbe:
    contact_ids: list[UUID] = field(default_factory=list)


@dataclass(frozen=True)
class TwoFarmContacts:
    user_a: User
    farm_a_id: UUID
    farm_b_id: UUID
    contact_a_id: UUID
    contact_b_id: UUID
    contact_a_name: str
    contact_b_name: str
    contact_b_notes: str


@pytest.fixture
def rollback_probe() -> RollbackProbe:
    return RollbackProbe()


@pytest_asyncio.fixture
async def test_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        os.environ["DATABASE_URL"],
        echo=False,
        hide_parameters=True,
        poolclass=NullPool,
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_connection(
    test_engine: AsyncEngine,
    rollback_probe: RollbackProbe,
) -> AsyncIterator[AsyncConnection]:
    try:
        connection = await test_engine.connect()
    except SQLAlchemyError as error:
        pytest.fail(
            "Could not connect to the validated local PostgreSQL test target "
            f"({type(error).__name__}); connection details were suppressed.",
            pytrace=False,
        )

    outer_transaction = await connection.begin()
    try:
        yield connection
    finally:
        if outer_transaction.is_active:
            await outer_transaction.rollback()
        await connection.close()

        if rollback_probe.contact_ids:
            verification_factory = async_sessionmaker(
                test_engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
            async with verification_factory() as verification_session:
                for contact_id in rollback_probe.contact_ids:
                    persisted_id = await verification_session.scalar(
                        select(Contact.id).where(Contact.id == contact_id)
                    )
                    assert persisted_id is None, (
                        "A contact committed inside the test transaction survived "
                        "outer-transaction rollback."
                    )


@pytest.fixture
def db_session_factory(
    db_connection: AsyncConnection,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=db_connection,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )


@pytest_asyncio.fixture
async def two_farm_contacts(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[TwoFarmContacts]:
    suffix = uuid4().hex
    user_a = User(
        id=uuid4(),
        email=f"farm-a-owner-{suffix}@example.test",
        password_hash="integration-test-only",
    )
    user_b = User(
        id=uuid4(),
        email=f"farm-b-owner-{suffix}@example.test",
        password_hash="integration-test-only",
    )
    farm_a_id = uuid4()
    farm_b_id = uuid4()
    farm_a = Farm(id=farm_a_id, owner_id=user_a.id, name=f"Farm A {suffix}")
    farm_b = Farm(id=farm_b_id, owner_id=user_b.id, name=f"Farm B {suffix}")
    contact_a_id = uuid4()
    contact_b_id = uuid4()
    contact_a_name = f"Farm A Contact {suffix}"
    contact_b_name = f"Farm B Private Contact {suffix}"
    contact_b_notes = f"Farm B private notes {suffix}"
    contact_a = Contact(
        id=contact_a_id,
        farm_id=farm_a_id,
        name=contact_a_name,
    )
    contact_b = Contact(
        id=contact_b_id,
        farm_id=farm_b_id,
        name=contact_b_name,
        notes=contact_b_notes,
    )

    async with db_session_factory() as session:
        session.add_all(
            [
                user_a,
                user_b,
                farm_a,
                farm_b,
                contact_a,
                contact_b,
                ContactRole(
                    id=uuid4(),
                    contact_id=contact_a_id,
                    role=ContactRoleEnum.CUSTOMER,
                ),
                ContactRole(
                    id=uuid4(),
                    contact_id=contact_b_id,
                    role=ContactRoleEnum.SUPPLIER,
                ),
            ]
        )
        await session.commit()

    yield TwoFarmContacts(
        user_a=user_a,
        farm_a_id=farm_a_id,
        farm_b_id=farm_b_id,
        contact_a_id=contact_a_id,
        contact_b_id=contact_b_id,
        contact_a_name=contact_a_name,
        contact_b_name=contact_b_name,
        contact_b_notes=contact_b_notes,
    )


@pytest.fixture
def test_app(
    db_session_factory: async_sessionmaker[AsyncSession],
    two_farm_contacts: TwoFarmContacts,
) -> Iterator[FastAPI]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(v1_router, prefix="/api/v1")
    session_connections: list[AsyncConnection] = []

    async def override_database_session() -> AsyncIterator[AsyncSession]:
        async with db_session_factory() as session:
            session_connections.append(await session.connection())
            yield session

    app.dependency_overrides[get_database_session] = override_database_session
    app.dependency_overrides[get_current_user] = lambda: two_farm_contacts.user_a
    app.state.test_database_session_connections = session_connections

    try:
        yield app
    finally:
        app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def api_client(test_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=test_app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        yield client
