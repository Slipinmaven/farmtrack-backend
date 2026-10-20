from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.dependencies.farm import get_owned_farm
from app.dependencies.services import get_sales_report_service
from app.models.farm import Farm
from app.schemas.enums import ProductType
from app.schemas.sales_report import SalesReportFilters, SalesReportResponse
from app.services.sales_report_service import SalesReportService

router = APIRouter(prefix="/farms/{farm_id}/sales", tags=["Sales"])


@router.get("", response_model=SalesReportResponse)
async def get_sales_report(
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[SalesReportService, Depends(get_sales_report_service)],
    from_date: date | None = None,
    to_date: date | None = None,
    category: ProductType | None = None,
    status: Literal["all", "completed", "cancelled"] = "completed",
    search: str | None = Query(default=None, max_length=150),
    include_daily: bool = False,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> SalesReportResponse:
    filters = SalesReportFilters(
        from_date=from_date,
        to_date=to_date,
        category=category,
        status=status,
        search=search,
    )
    return await service.get_report(
        farm.id,
        filters,
        offset,
        limit,
        include_daily=include_daily,
    )
