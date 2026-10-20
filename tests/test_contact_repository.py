from uuid import uuid4

import pytest
from sqlalchemy.dialects import sqlite

from app.models.contact import Contact
from app.models.contact_roles import ContactRole
from app.repositories.contact_repository import ContactRepository
from app.schemas.enums import ContactRoleEnum


class FakeResult:
    def scalars(self):
        return self

    def all(self):
        return []


class FakeSession:
    def __init__(self):
        self.query = None

    async def execute(self, query):
        self.query = query
        return FakeResult()


@pytest.mark.asyncio
async def test_list_by_farm_filters_customer_search_and_caps_results():
    session = FakeSession()
    repository = ContactRepository(session=session)

    await repository.list_by_farm(
        uuid4(),
        search="  Mae  ",
        role=ContactRoleEnum.CUSTOMER,
        limit=25,
        offset=50,
    )

    sql = str(session.query.compile(dialect=sqlite.dialect()))
    assert f"{Contact.__tablename__}.name" in sql
    assert f"{ContactRole.__tablename__}.role" in sql
    assert "LIMIT" in sql
    assert "OFFSET" in sql
    assert "%Mae%" in session.query.compile(dialect=sqlite.dialect()).params.values()
