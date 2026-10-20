from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.dependencies.farm import get_owned_farm
from app.dependencies.services import get_expense_service
from app.models.farm import Farm
from app.schemas.expense import (
    ExpenseCancelRequest,
    ExpenseCategoryCreateRequest,
    ExpenseCategoryResponse,
    ExpenseCategoryUpdateRequest,
    ExpenseCreateRequest,
    ExpenseListResponse,
    ExpensePaymentCreateRequest,
    ExpenseRefundCreateRequest,
    ExpenseResponse,
    ExpenseSummaryResponse,
    ExpenseUpdateRequest,
)
from app.services.expense_service import ExpenseService

router = APIRouter(
    prefix="/farms/{farm_id}/expenses",
    tags=["Expenses"],
)


@router.get("", response_model=ExpenseListResponse)
async def list_expenses(
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[ExpenseService, Depends(get_expense_service)],
    category: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    contact_id: Annotated[UUID | None, Query()] = None,
    block_id: Annotated[UUID | None, Query()] = None,
    from_date: Annotated[date | None, Query()] = None,
    to_date: Annotated[date | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    payment_status: Annotated[
        Literal["all", "paid", "partial", "unpaid", "cancelled"],
        Query(),
    ] = "all",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> ExpenseListResponse:
    return await service.list_expenses(
        farm,
        category=category,
        contact_id=contact_id,
        block_id=block_id,
        from_date=from_date,
        to_date=to_date,
        search=search,
        payment_status=None if payment_status == "all" else payment_status,
        offset=offset,
        limit=limit,
    )


@router.post("", response_model=ExpenseResponse, status_code=status.HTTP_201_CREATED)
async def create_expense(
    request: ExpenseCreateRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[ExpenseService, Depends(get_expense_service)],
) -> ExpenseResponse:
    return await service.create_expense(farm, request)


@router.get("/categories", response_model=list[ExpenseCategoryResponse])
async def list_expense_categories(
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[ExpenseService, Depends(get_expense_service)],
    include_inactive: Annotated[bool, Query()] = False,
) -> list[ExpenseCategoryResponse]:
    return await service.list_categories(farm, include_inactive=include_inactive)


@router.post(
    "/categories",
    response_model=ExpenseCategoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_expense_category(
    request: ExpenseCategoryCreateRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[ExpenseService, Depends(get_expense_service)],
) -> ExpenseCategoryResponse:
    return await service.create_category(farm, request)


@router.patch("/categories/{category_id}", response_model=ExpenseCategoryResponse)
async def update_expense_category(
    category_id: UUID,
    request: ExpenseCategoryUpdateRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[ExpenseService, Depends(get_expense_service)],
) -> ExpenseCategoryResponse:
    return await service.update_category(farm, category_id, request)


@router.get("/summary", response_model=ExpenseSummaryResponse)
async def get_expense_summary(
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[ExpenseService, Depends(get_expense_service)],
    from_date: Annotated[date | None, Query()] = None,
    to_date: Annotated[date | None, Query()] = None,
) -> ExpenseSummaryResponse:
    return await service.get_expense_summary(
        farm,
        from_date=from_date,
        to_date=to_date,
    )


@router.get("/{expense_id}", response_model=ExpenseResponse)
async def get_expense(
    expense_id: UUID,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[ExpenseService, Depends(get_expense_service)],
) -> ExpenseResponse:
    return await service.get_expense(farm, expense_id)


@router.patch("/{expense_id}", response_model=ExpenseResponse)
async def update_expense(
    expense_id: UUID,
    request: ExpenseUpdateRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[ExpenseService, Depends(get_expense_service)],
) -> ExpenseResponse:
    return await service.update_expense(farm, expense_id, request)


@router.post(
    "/{expense_id}/payments",
    response_model=ExpenseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_expense_payment(
    expense_id: UUID,
    request: ExpensePaymentCreateRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[ExpenseService, Depends(get_expense_service)],
) -> ExpenseResponse:
    return await service.record_payment(farm, expense_id, request)


@router.post(
    "/{expense_id}/refunds",
    response_model=ExpenseResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_expense_refund(
    expense_id: UUID,
    request: ExpenseRefundCreateRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[ExpenseService, Depends(get_expense_service)],
) -> ExpenseResponse:
    return await service.record_refund(farm, expense_id, request)


@router.post("/{expense_id}/cancel", response_model=ExpenseResponse)
async def cancel_expense(
    expense_id: UUID,
    request: ExpenseCancelRequest,
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[ExpenseService, Depends(get_expense_service)],
) -> ExpenseResponse:
    return await service.cancel_expense(farm, expense_id, request)