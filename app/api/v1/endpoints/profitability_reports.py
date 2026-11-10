from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies.farm import get_owned_farm
from app.presentation.dependencies.services import get_profitability_report_service
from app.models.farm import Farm
from app.schemas.profitability_report import (
    EggProductionCostConfirmationRequest,
    EggProductionCostConfirmationResponse,
    ProfitabilityReportResponse,
    ProfitabilityStockValuationRequest,
    ProfitabilityStockValuationResponse,
)
from app.services.profitability_report_service import ProfitabilityReportService


router = APIRouter(
    prefix="/farms/{farm_id}/reports",
    tags=["Reports"],
)


@router.get("/profitability", response_model=ProfitabilityReportResponse)
async def get_profitability_report(
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        ProfitabilityReportService,
        Depends(get_profitability_report_service),
    ],
    from_date: Annotated[date, Query()],
    to_date: Annotated[date, Query()],
) -> ProfitabilityReportResponse:
    if from_date > to_date:
        raise HTTPException(
            status_code=422,
            detail="from_date must be on or before to_date.",
        )
    return await service.build_report(
        farm.id,
        from_date=from_date,
        to_date=to_date,
    )


@router.post(
    "/profitability/confirm-zero-egg-production-cost",
    response_model=EggProductionCostConfirmationResponse,
)
async def confirm_zero_egg_production_cost(
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        ProfitabilityReportService,
        Depends(get_profitability_report_service),
    ],
    request: EggProductionCostConfirmationRequest,
) -> EggProductionCostConfirmationResponse:
    return await service.confirm_zero_egg_production_cost(
        farm.id,
        user_id=farm.owner_id,
        from_date=request.from_date,
        to_date=request.to_date,
    )


@router.post(
    "/profitability/stock-valuation",
    response_model=ProfitabilityStockValuationResponse,
)
async def record_profitability_stock_valuation(
    farm: Annotated[Farm, Depends(get_owned_farm)],
    service: Annotated[
        ProfitabilityReportService,
        Depends(get_profitability_report_service),
    ],
    request: ProfitabilityStockValuationRequest,
) -> ProfitabilityStockValuationResponse:
    return await service.record_stock_valuation(
        farm.id,
        user_id=farm.owner_id,
        request=request,
    )
