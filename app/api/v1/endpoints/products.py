from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.dependencies.farm import get_owned_farm
from app.dependencies.services import get_product_service
from app.models.farm import Farm
from app.schemas.product import ProductCreateRequest, ProductResponse, ProductUpdateRequest
from app.services.product_service import ProductService


router = APIRouter(
    prefix="/farms/{farm_id}/products",
    tags=["Products"],
)


@router.get("", response_model=list[ProductResponse])
async def list_products(
    farm: Farm = Depends(get_owned_farm),
    service: ProductService = Depends(get_product_service),
    search: Annotated[str | None, Query()] = None,
) -> list[ProductResponse]:
    return await service.list_products(farm, search=search)


@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    request: ProductCreateRequest,
    farm: Farm = Depends(get_owned_farm),
    service: ProductService = Depends(get_product_service),
) -> ProductResponse:
    return await service.create_product(farm, request)


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: UUID,
    farm: Farm = Depends(get_owned_farm),
    service: ProductService = Depends(get_product_service),
) -> ProductResponse:
    return await service.get_product(farm, product_id)


@router.patch("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: UUID,
    request: ProductUpdateRequest,
    farm: Farm = Depends(get_owned_farm),
    service: ProductService = Depends(get_product_service),
) -> ProductResponse:
    return await service.update_product(farm, product_id, request)


@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_product(
    product_id: UUID,
    farm: Farm = Depends(get_owned_farm),
    service: ProductService = Depends(get_product_service),
) -> Response:
    await service.delete_product(farm, product_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
