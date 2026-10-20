from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.dependencies.farm import get_owned_farm
from app.dependencies.services import (
    get_contact_history_service,
    get_contact_service,
)
from app.models.farm import Farm
from app.schemas.contact import (
    ContactCreateRequest,
    ContactResponse,
    ContactRoleCreateRequest,
    ContactRoleProductCreateRequest,
    ContactRoleProductResponse,
    ContactRoleResponse,
    ContactRoleUpdateRequest,
    ContactUpdateRequest,
    ContactTransactionHistoryResponse,
)
from app.schemas.enums import ContactRoleEnum
from app.services.contact_service import ContactService
from app.services.contact_history_service import ContactHistoryService


router = APIRouter(
    prefix="/farms/{farm_id}/contacts",
    tags=["Contacts"],
)


@router.get("", response_model=list[ContactResponse])
async def list_contacts(
    farm: Farm = Depends(get_owned_farm),
    service: ContactService = Depends(get_contact_service),
    search: Annotated[str | None, Query()] = None,
    role: Annotated[ContactRoleEnum | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ContactResponse]:
    return await service.list_contacts(
        farm,
        search=search,
        role=role,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=ContactResponse, status_code=status.HTTP_201_CREATED)
async def create_contact(
    request: ContactCreateRequest,
    farm: Farm = Depends(get_owned_farm),
    service: ContactService = Depends(get_contact_service),
) -> ContactResponse:
    return await service.create_contact(farm, request)


@router.get("/{contact_id}", response_model=ContactResponse)
async def get_contact(
    contact_id: UUID,
    farm: Farm = Depends(get_owned_farm),
    service: ContactService = Depends(get_contact_service),
) -> ContactResponse:
    return await service.get_contact(farm, contact_id)


@router.get(
    "/{contact_id}/transactions",
    response_model=ContactTransactionHistoryResponse,
)
async def get_contact_transaction_history(
    contact_id: UUID,
    farm: Farm = Depends(get_owned_farm),
    service: ContactHistoryService = Depends(get_contact_history_service),
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ContactTransactionHistoryResponse:
    return await service.get_history(
        farm.id,
        contact_id,
        limit=limit,
        offset=offset,
    )


@router.patch("/{contact_id}", response_model=ContactResponse)
async def update_contact(
    contact_id: UUID,
    request: ContactUpdateRequest,
    farm: Farm = Depends(get_owned_farm),
    service: ContactService = Depends(get_contact_service),
) -> ContactResponse:
    return await service.update_contact(farm, contact_id, request)


@router.delete(
    "/{contact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_contact(
    contact_id: UUID,
    farm: Farm = Depends(get_owned_farm),
    service: ContactService = Depends(get_contact_service),
) -> Response:
    await service.delete_contact(farm, contact_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{contact_id}/roles", response_model=list[ContactRoleResponse])
async def list_contact_roles(
    contact_id: UUID,
    farm: Farm = Depends(get_owned_farm),
    service: ContactService = Depends(get_contact_service),
) -> list[ContactRoleResponse]:
    return await service.list_contact_roles(farm, contact_id)


@router.post(
    "/{contact_id}/roles",
    response_model=ContactRoleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_contact_role(
    contact_id: UUID,
    request: ContactRoleCreateRequest,
    farm: Farm = Depends(get_owned_farm),
    service: ContactService = Depends(get_contact_service),
) -> ContactRoleResponse:
    return await service.create_contact_role(farm, contact_id, request)


@router.get(
    "/{contact_id}/roles/{role_id}",
    response_model=ContactRoleResponse,
)
async def get_contact_role(
    contact_id: UUID,
    role_id: UUID,
    farm: Farm = Depends(get_owned_farm),
    service: ContactService = Depends(get_contact_service),
) -> ContactRoleResponse:
    return await service.get_contact_role(farm, contact_id, role_id)


@router.patch(
    "/{contact_id}/roles/{role_id}",
    response_model=ContactRoleResponse,
)
async def update_contact_role(
    contact_id: UUID,
    role_id: UUID,
    request: ContactRoleUpdateRequest,
    farm: Farm = Depends(get_owned_farm),
    service: ContactService = Depends(get_contact_service),
) -> ContactRoleResponse:
    return await service.update_contact_role(farm, contact_id, role_id, request)


@router.delete(
    "/{contact_id}/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_contact_role(
    contact_id: UUID,
    role_id: UUID,
    farm: Farm = Depends(get_owned_farm),
    service: ContactService = Depends(get_contact_service),
) -> Response:
    await service.delete_contact_role(farm, contact_id, role_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{contact_id}/roles/{role_id}/products",
    response_model=list[ContactRoleProductResponse],
)
async def list_role_products(
    contact_id: UUID,
    role_id: UUID,
    farm: Farm = Depends(get_owned_farm),
    service: ContactService = Depends(get_contact_service),
) -> list[ContactRoleProductResponse]:
    return await service.list_role_products(farm, contact_id, role_id)


@router.post(
    "/{contact_id}/roles/{role_id}/products",
    response_model=ContactRoleProductResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_product_to_role(
    contact_id: UUID,
    role_id: UUID,
    request: ContactRoleProductCreateRequest,
    farm: Farm = Depends(get_owned_farm),
    service: ContactService = Depends(get_contact_service),
) -> ContactRoleProductResponse:
    return await service.add_product_to_role(farm, contact_id, role_id, request)


@router.delete(
    "/{contact_id}/roles/{role_id}/products/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def remove_product_from_role(
    contact_id: UUID,
    role_id: UUID,
    product_id: UUID,
    farm: Farm = Depends(get_owned_farm),
    service: ContactService = Depends(get_contact_service),
) -> Response:
    await service.remove_product_from_role(farm, contact_id, role_id, product_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)