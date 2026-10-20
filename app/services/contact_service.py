from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.core.logging import get_application_logger
from app.core.unit_of_work import UnitOfWork
from app.models.contact import Contact
from app.models.contact_role_products import ContactRoleProduct
from app.models.contact_roles import ContactRole
from app.models.farm import Farm
from app.models.products import Product
from app.repositories.contact_repository import ContactRepository
from app.repositories.contact_role_repository import ContactRoleRepository
from app.repositories.contact_role_product_repository import ContactRoleProductRepository
from app.schemas.contact import (
    ContactCreateRequest,
    ContactResponse,
    ContactRoleCreateRequest,
    ContactRoleProductCreateRequest,
    ContactRoleProductResponse,
    ContactRoleResponse,
    ContactRoleUpdateRequest,
    ContactUpdateRequest,
)
from app.schemas.enums import ContactRoleEnum
from app.schemas.enums import ActivityEntityType, ActivityType
from app.services.activity_service import ActivityService
from app.services.activity_details import activity_field_changes

app_logger = get_application_logger()


def _is_duplicate_contact_role(error: IntegrityError) -> bool:
    original_error = error.orig
    while original_error is not None:
        constraint_name = getattr(original_error, "constraint_name", None)
        if constraint_name is None:
            constraint_name = getattr(
                getattr(original_error, "diag", None),
                "constraint_name",
                None,
            )
        if constraint_name == "uq_contact_roles_contact_id_role":
            return True
        original_error = original_error.__cause__ or original_error.__context__
    return False


def _is_duplicate_contact_role_product(error: IntegrityError) -> bool:
    original_error = error.orig
    while original_error is not None:
        constraint_name = getattr(original_error, "constraint_name", None)
        if constraint_name is None:
            constraint_name = getattr(
                getattr(original_error, "diag", None),
                "constraint_name",
                None,
            )
        if constraint_name == "uq_contact_role_products_contact_role_id_product_id":
            return True
        original_error = original_error.__cause__ or original_error.__context__
    return False


class ContactService:
    def __init__(
        self,
        contact_repository: ContactRepository,
        contact_role_repository: ContactRoleRepository,
        contact_role_product_repository: ContactRoleProductRepository,
        activity_service: ActivityService,
        unit_of_work: UnitOfWork,
    ):
        self.contact_repository = contact_repository
        self.contact_role_repository = contact_role_repository
        self.contact_role_product_repository = contact_role_product_repository
        self.activity_service = activity_service
        self.unit_of_work = unit_of_work

    async def list_contacts(
        self,
        farm: Farm,
        search: str | None = None,
        role: ContactRoleEnum | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ContactResponse]:
        async with self.unit_of_work:
            contacts = await self.contact_repository.list_by_farm(
                farm.id,
                search,
                role=role,
                limit=limit,
                offset=offset,
            )
            app_logger.info(
                "contacts_listed",
                extra={"event": "contacts_listed", "user_id": farm.owner_id, "farm_id": farm.id},
            )
            return [
                self._to_contact_response(contact)
                for contact in contacts
            ]

    async def get_contact(self, farm: Farm, contact_id: UUID) -> ContactResponse:
        async with self.unit_of_work:
            contact = await self._get_contact_or_raise(farm.id, contact_id)
            response = self._to_contact_response(contact)
            app_logger.info(
                "contact_retrieved",
                extra={"event": "contact_retrieved", "user_id": farm.owner_id, "farm_id": farm.id},
            )
            return response

    async def create_contact(
        self,
        farm: Farm,
        contact_data: ContactCreateRequest,
    ) -> ContactResponse:
        async with self.unit_of_work:
            contact = await self.contact_repository.create(
                farm.id,
                contact_data.model_dump(exclude={"role"}),
            )
            contact_role = await self.contact_role_repository.create(
                contact.id,
                contact_data.role,
            )
            await self.activity_service.record(
                farm_id=farm.id,
                user_id=farm.owner_id,
                activity_type=ActivityType.CONTACT_CREATED,
                entity_type=ActivityEntityType.CONTACT,
                entity_id=contact.id,
                details={
                    "name": contact.name,
                    "role": contact_role.role.value,
                    "phone": contact.phone,
                    "email": contact.email,
                    "address": contact.address,
                    "notes": contact.notes,
                },
            )
            await self.unit_of_work.commit()
            response = self._to_contact_response(contact, [contact_role])
            app_logger.info(
                "contact_created",
                extra={"event": "contact_created", "user_id": farm.owner_id, "farm_id": farm.id},
            )
            return response

    async def update_contact(
        self,
        farm: Farm,
        contact_id: UUID,
        contact_data: ContactUpdateRequest,
    ) -> ContactResponse:
        async with self.unit_of_work:
            contact = await self._get_contact_or_raise(farm.id, contact_id)
            update_data = contact_data.model_dump(exclude_unset=True)
            before_values = {
                field: getattr(contact, field) for field in update_data
            }
            for field, value in update_data.items():
                setattr(contact, field, value)
            contact = await self.contact_repository.update(contact)
            contact_roles = await self.contact_role_repository.list_by_contact(contact.id)
            changes = activity_field_changes(
                before_values,
                {field: getattr(contact, field) for field in update_data},
            )
            if changes:
                details: dict[str, object] = {
                    "name": contact.name,
                    "changes": changes,
                }
                await self.activity_service.record(
                    farm_id=farm.id,
                    user_id=farm.owner_id,
                    activity_type=ActivityType.CONTACT_UPDATED,
                    entity_type=ActivityEntityType.CONTACT,
                    entity_id=contact.id,
                    details=details,
                )
            await self.unit_of_work.commit()
            response = self._to_contact_response(contact, contact_roles)
            app_logger.info(
                "contact_updated",
                extra={"event": "contact_updated", "user_id": farm.owner_id, "farm_id": farm.id},
            )
            return response

    async def delete_contact(self, farm: Farm, contact_id: UUID) -> None:
        async with self.unit_of_work:
            contact = await self._get_contact_or_raise(farm.id, contact_id)
            await self.contact_repository.delete(contact)
            await self.activity_service.record(
                farm_id=farm.id,
                user_id=farm.owner_id,
                activity_type=ActivityType.CONTACT_DELETED,
                entity_type=ActivityEntityType.CONTACT,
                entity_id=contact.id,
                details={
                    "name": contact.name,
                    "phone": contact.phone,
                    "email": contact.email,
                    "address": contact.address,
                    "notes": contact.notes,
                },
            )
            await self.unit_of_work.commit()
            app_logger.info(
                "contact_deleted",
                extra={"event": "contact_deleted", "user_id": farm.owner_id, "farm_id": farm.id},
            )

    async def list_contact_roles(
        self,
        farm: Farm,
        contact_id: UUID,
    ) -> list[ContactRoleResponse]:
        async with self.unit_of_work:
            await self._get_contact_or_raise(farm.id, contact_id)
            roles = await self.contact_role_repository.list_by_contact(contact_id)
            return [
                ContactRoleResponse.model_validate(role, from_attributes=True)
                for role in roles
            ]

    async def get_contact_role(
        self,
        farm: Farm,
        contact_id: UUID,
        role_id: UUID,
    ) -> ContactRoleResponse:
        async with self.unit_of_work:
            await self._get_contact_or_raise(farm.id, contact_id)
            role = await self._get_role_or_raise(contact_id, role_id)
            return ContactRoleResponse.model_validate(role, from_attributes=True)

    async def create_contact_role(
        self,
        farm: Farm,
        contact_id: UUID,
        role_data: ContactRoleCreateRequest,
    ) -> ContactRoleResponse:
        try:
            async with self.unit_of_work:
                contact = await self._get_contact_or_raise(farm.id, contact_id)
                role = await self.contact_role_repository.create(
                    contact_id,
                    role_data.role,
                )
                await self.activity_service.record(
                    farm_id=farm.id,
                    user_id=farm.owner_id,
                    activity_type=ActivityType.CONTACT_ROLE_CREATED,
                    entity_type=ActivityEntityType.CONTACT_ROLE,
                    entity_id=role.id,
                    details={
                        "contact_id": str(contact.id),
                        "contact_name": contact.name,
                        "role": role.role.value,
                    },
                )
                await self.unit_of_work.commit()
                response = ContactRoleResponse.model_validate(role, from_attributes=True)
                app_logger.info(
                    "contact_role_created",
                    extra={"event": "contact_role_created", "user_id": farm.owner_id, "farm_id": farm.id},
                )
                return response
        except IntegrityError as exc:
            if _is_duplicate_contact_role(exc):
                raise ConflictError("This contact already has that role.") from exc
            raise

    async def update_contact_role(
        self,
        farm: Farm,
        contact_id: UUID,
        role_id: UUID,
        role_data: ContactRoleUpdateRequest,
    ) -> ContactRoleResponse:
        try:
            async with self.unit_of_work:
                contact = await self._get_contact_or_raise(farm.id, contact_id)
                role = await self._get_role_or_raise(contact_id, role_id)
                previous_role = role.role.value
                if role_data.role is not None:
                    role.role = role_data.role
                role = await self.contact_role_repository.update(role)
                if previous_role != role.role.value:
                    await self.activity_service.record(
                        farm_id=farm.id,
                        user_id=farm.owner_id,
                        activity_type=ActivityType.CONTACT_ROLE_UPDATED,
                        entity_type=ActivityEntityType.CONTACT_ROLE,
                        entity_id=role.id,
                        details={
                            "contact_id": str(contact.id),
                            "contact_name": contact.name,
                            "changes": [
                                {
                                    "field": "role",
                                    "from": previous_role,
                                    "to": role.role.value,
                                }
                            ],
                        },
                    )
                await self.unit_of_work.commit()
                response = ContactRoleResponse.model_validate(role, from_attributes=True)
                app_logger.info(
                    "contact_role_updated",
                    extra={"event": "contact_role_updated", "user_id": farm.owner_id, "farm_id": farm.id},
                )
                return response
        except IntegrityError as exc:
            if _is_duplicate_contact_role(exc):
                raise ConflictError("This contact already has that role.") from exc
            raise

    async def delete_contact_role(
        self,
        farm: Farm,
        contact_id: UUID,
        role_id: UUID,
    ) -> None:
        async with self.unit_of_work:
            contact = await self._get_contact_or_raise(farm.id, contact_id)
            role = await self._get_role_or_raise(contact_id, role_id)
            role_name = role.role.value
            await self.contact_role_repository.delete(role)
            await self.activity_service.record(
                farm_id=farm.id,
                user_id=farm.owner_id,
                activity_type=ActivityType.CONTACT_ROLE_DELETED,
                entity_type=ActivityEntityType.CONTACT_ROLE,
                entity_id=role.id,
                details={
                    "contact_id": str(contact.id),
                    "contact_name": contact.name,
                    "role": role_name,
                },
            )
            await self.unit_of_work.commit()
            app_logger.info(
                "contact_role_deleted",
                extra={"event": "contact_role_deleted", "user_id": farm.owner_id, "farm_id": farm.id},
            )

    async def list_role_products(
        self,
        farm: Farm,
        contact_id: UUID,
        role_id: UUID,
    ) -> list[ContactRoleProductResponse]:
        async with self.unit_of_work:
            contact = await self._get_contact_or_raise(farm.id, contact_id)
            role = await self._get_role_or_raise(contact.id, role_id)
            associations = await self.contact_role_product_repository.list_for_role(role.id)
            if any(product.farm_id != farm.id for _, product in associations):
                raise ResourceNotFoundError("Associated product not found.")
            return [
                self._to_role_product_response(association, product)
                for association, product in associations
            ]

    async def add_product_to_role(
        self,
        farm: Farm,
        contact_id: UUID,
        role_id: UUID,
        request: ContactRoleProductCreateRequest,
    ) -> ContactRoleProductResponse:
        try:
            async with self.unit_of_work:
                contact = await self._get_contact_or_raise(farm.id, contact_id)
                role = await self._get_role_or_raise(contact.id, role_id)
                product = await self._get_product_for_farm(farm.id, request.product_id)
                if not product.is_active:
                    raise ConflictError("Inactive products cannot be newly associated.")

                existing = await self.contact_role_product_repository.get_association(
                    role.id,
                    product.id,
                )
                if existing is not None:
                    raise ConflictError("This product is already associated with the contact role.")

                association = await self.contact_role_product_repository.create(
                    role.id,
                    product.id,
                )
                await self.activity_service.record(
                    farm_id=farm.id,
                    user_id=farm.owner_id,
                    activity_type=ActivityType.CONTACT_ROLE_PRODUCT_ADDED,
                    entity_type=ActivityEntityType.CONTACT_ROLE_PRODUCT,
                    entity_id=association.id,
                    details={
                        "contact_name": contact.name,
                        "role": role.role.value,
                        "contact_id": str(contact.id),
                        "role_id": str(role.id),
                        "product_name": product.name,
                        "product_id": str(product.id),
                    },
                )
                await self.unit_of_work.commit()
                app_logger.info(
                    "contact_role_product_added",
                    extra={"event": "contact_role_product_added", "user_id": farm.owner_id, "farm_id": farm.id},
                )
                return self._to_role_product_response(association, product)
        except IntegrityError as exc:
            if _is_duplicate_contact_role_product(exc):
                raise ConflictError(
                    "This product is already associated with the contact role."
                ) from exc
            raise

    async def remove_product_from_role(
        self,
        farm: Farm,
        contact_id: UUID,
        role_id: UUID,
        product_id: UUID,
    ) -> None:
        async with self.unit_of_work:
            contact = await self._get_contact_or_raise(farm.id, contact_id)
            role = await self._get_role_or_raise(contact.id, role_id)
            association = await self.contact_role_product_repository.get_association(
                role.id,
                product_id,
            )
            if association is None:
                raise ResourceNotFoundError("Product association not found.")
            product = await self._get_product_for_farm(farm.id, product_id)
            await self.contact_role_product_repository.delete(association)
            await self.activity_service.record(
                farm_id=farm.id,
                user_id=farm.owner_id,
                activity_type=ActivityType.CONTACT_ROLE_PRODUCT_REMOVED,
                entity_type=ActivityEntityType.CONTACT_ROLE_PRODUCT,
                entity_id=association.id,
                details={
                    "contact_name": contact.name,
                    "role": role.role.value,
                    "contact_id": str(contact.id),
                    "role_id": str(role.id),
                    "product_name": product.name,
                    "product_id": str(product.id),
                },
            )
            await self.unit_of_work.commit()
            app_logger.info(
                "contact_role_product_removed",
                extra={"event": "contact_role_product_removed", "user_id": farm.owner_id, "farm_id": farm.id},
            )

    async def _get_contact_or_raise(self, farm_id: UUID, contact_id: UUID) -> Contact:
        contact = await self.contact_repository.get_by_id(farm_id, contact_id)
        if contact is None:
            raise ResourceNotFoundError("Contact not found.")
        return contact

    @staticmethod
    def _to_contact_response(
        contact: Contact,
        contact_roles: list[ContactRole] | None = None,
    ) -> ContactResponse:
        roles = contact_roles if contact_roles is not None else contact.contact_roles
        return ContactResponse(
            id=contact.id,
            farm_id=contact.farm_id,
            name=contact.name,
            roles=[contact_role.role for contact_role in roles],
            phone=contact.phone,
            email=contact.email,
            address=contact.address,
            notes=contact.notes,
            created_at=contact.created_at,
            updated_at=contact.updated_at,
        )

    async def _get_role_or_raise(
        self,
        contact_id: UUID,
        role_id: UUID,
    ) -> ContactRole:
        role = await self.contact_role_repository.get_by_id(contact_id, role_id)
        if role is None:
            raise ResourceNotFoundError("Contact role not found.")
        return role

    async def _get_product_for_farm(self, farm_id: UUID, product_id: UUID) -> Product:
        product = await self.contact_role_product_repository.get_product(product_id)
        if product is None or product.farm_id != farm_id:
            raise ResourceNotFoundError("Product not found.")
        return product

    @staticmethod
    def _to_role_product_response(
        association: ContactRoleProduct,
        product: Product,
    ) -> ContactRoleProductResponse:
        return ContactRoleProductResponse(
            association_id=association.id,
            product_id=product.id,
            product_name=product.name,
            product_type=product.product_type,
            is_active=product.is_active,
            created_at=association.created_at,
        )