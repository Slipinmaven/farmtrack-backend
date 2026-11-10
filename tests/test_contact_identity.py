from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError
from app.models.contact import Contact
from app.schemas.contact import ContactCreateRequest, ContactUpdateRequest
from app.schemas.enums import ContactRoleEnum
from app.services.contact_service import (
    ContactService,
    _duplicate_contact_field,
    _normalize_contact_email,
    _normalize_contact_phone,
)


class FakeUnitOfWork:
    async def __aenter__(self):
        return self

    async def __aexit__(self, _exc_type, _exc_value, _traceback):
        return None


class FakeUniqueViolation(Exception):
    def __init__(self, constraint_name: str):
        super().__init__(constraint_name)
        self.constraint_name = constraint_name


def create_service():
    contact_repository = SimpleNamespace(
        phone_is_in_use=AsyncMock(return_value=False),
        email_is_in_use=AsyncMock(return_value=False),
        create=AsyncMock(),
        update=AsyncMock(),
    )
    service = ContactService(
        contact_repository=contact_repository,
        contact_role_repository=SimpleNamespace(),
        contact_role_product_repository=None,
        activity_service=None,
        unit_of_work=FakeUnitOfWork(),
    )
    return service, contact_repository


def test_contact_identity_normalization_ignores_phone_format_and_email_case():
    assert _normalize_contact_phone("+1 (415) 555-0100") == "14155550100"
    assert _normalize_contact_phone(" -- ") is None
    assert _normalize_contact_email("  Person@Example.com ") == "person@example.com"
    assert _normalize_contact_email(" ") is None


def test_contact_table_enforces_unique_farm_scoped_identity_keys():
    constraint_names = {
        constraint.name for constraint in Contact.__table__.constraints
    }

    assert "uq_contacts_farm_phone_normalized" in constraint_names
    assert "uq_contacts_farm_email_normalized" in constraint_names


def test_unique_constraint_errors_are_classified_for_presentable_conflicts():
    phone_error = IntegrityError(
        "insert",
        {},
        orig=FakeUniqueViolation("uq_contacts_farm_phone_normalized"),
    )
    email_error = IntegrityError(
        "insert",
        {},
        orig=FakeUniqueViolation("uq_contacts_farm_email_normalized"),
    )

    assert _duplicate_contact_field(phone_error) == "phone"
    assert _duplicate_contact_field(email_error) == "email"


@pytest.mark.asyncio
async def test_create_contact_rejects_duplicate_phone_before_creating_record():
    service, repository = create_service()
    repository.phone_is_in_use.return_value = True
    farm = SimpleNamespace(id=uuid4(), owner_id=uuid4())

    with pytest.raises(ConflictError, match="phone number is already used"):
        await service.create_contact(
            farm,
            ContactCreateRequest(
                name="New contact",
                role=ContactRoleEnum.CUSTOMER,
                phone="(415) 555-0100",
            ),
        )

    repository.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_contact_rejects_duplicate_email_and_excludes_current_contact():
    service, repository = create_service()
    repository.email_is_in_use.return_value = True
    farm_id = uuid4()
    contact_id = uuid4()
    service._get_contact_or_raise = AsyncMock(
        return_value=SimpleNamespace(
            id=contact_id,
            phone_normalized=None,
            email_normalized="old@example.com",
        )
    )

    with pytest.raises(ConflictError, match="email address is already used"):
        await service.update_contact(
            SimpleNamespace(id=farm_id, owner_id=uuid4()),
            contact_id,
            ContactUpdateRequest(email="New@Example.com"),
        )

    repository.email_is_in_use.assert_awaited_once_with(
        farm_id,
        "new@example.com",
        contact_id,
    )
    repository.update.assert_not_awaited()
