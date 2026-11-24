from datetime import datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.core.exceptions import AppError
from app.models.farm import Farm
from app.services.ai_assistant.contracts import FarmOperationsSummaryToolArguments
from app.services.ai_assistant.service_context import AssistantServiceContext


class FarmAssistantOperationsMixin(AssistantServiceContext):
    async def _farm_operations_summary(
        self,
        farm: Farm,
        parsed: FarmOperationsSummaryToolArguments,
    ) -> dict[str, Any]:
        from_date = parsed.from_date
        to_date = parsed.to_date
        if from_date is None or to_date is None:
            raise AppError(
                "AI_ASSISTANT_INVALID_DATE_RANGE",
                "A date range could not be resolved.",
                422,
            )

        block_service = self.block_service
        product_service = self.product_service
        chicken_loss_service = self.chicken_loss_service
        chicken_movement_service = self.chicken_movement_service
        egg_collection_service = self.egg_collection_service
        egg_loss_service = self.egg_loss_service
        product_consumption_service = self.product_consumption_service
        if (
            block_service is None
            or product_service is None
            or chicken_loss_service is None
            or chicken_movement_service is None
            or egg_collection_service is None
            or egg_loss_service is None
            or product_consumption_service is None
        ):
            raise AppError(
                "AI_ASSISTANT_UNAVAILABLE",
                "The farm operations read tools are not configured.",
                503,
            )

        block_id: UUID | None = None
        block_name: str | None = None
        if parsed.block_name is not None:
            matching_blocks = await block_service.list_blocks(
                farm,
                search=parsed.block_name,
            )
            exact_matches = [
                block
                for block in matching_blocks
                if block.name.strip().casefold()
                == parsed.block_name.strip().casefold()
            ]
            if len(exact_matches) != 1:
                return {
                    "block_match_status": (
                        "ambiguous" if exact_matches else "not_found"
                    ),
                    "requested_block": parsed.block_name,
                    "candidate_blocks": [
                        block.name for block in exact_matches or matching_blocks[:20]
                    ],
                }
            block_id = exact_matches[0].id
            block_name = exact_matches[0].name

        products = await product_service.list_products(farm)
        product_details: dict[
            UUID,
            tuple[str, str, str | None, str | None],
        ] = {}
        for product in products:
            base_unit = next(
                (
                    unit
                    for unit in product.product_units
                    if unit.is_base_unit
                ),
                None,
            )
            product_details[product.id] = (
                product.name,
                str(product.product_type.value),
                base_unit.unit_name if base_unit else None,
                base_unit.unit_abbreviation if base_unit else None,
            )

        timezone = ZoneInfo(settings.timezone)
        from_datetime = datetime.combine(
            from_date,
            time.min,
            tzinfo=timezone,
        )
        to_datetime = datetime.combine(
            to_date,
            time.max,
            tzinfo=timezone,
        )
        collections = await egg_collection_service.list_collections(
            farm,
            block_id=block_id,
            from_datetime=from_datetime,
            to_datetime=to_datetime,
        )
        collection_totals: dict[UUID, Decimal] = {}
        collection_count = 0
        for collection in collections:
            if collection.entry_type != "collection":
                continue
            collection_count += 1
            collection_totals[collection.product_id] = (
                collection_totals.get(collection.product_id, Decimal("0"))
                + collection.quantity_in_base_unit
            )

        chicken_losses = await chicken_loss_service.list_losses(
            farm,
            block_id=block_id,
            from_date=from_date,
            to_date=to_date,
        )
        chicken_loss_reasons: dict[str, dict[str, int]] = {}
        total_chickens_lost = 0
        for loss in chicken_losses:
            reason = loss.reason.value
            totals = chicken_loss_reasons.setdefault(
                reason,
                {"record_count": 0, "chickens": 0},
            )
            totals["record_count"] += 1
            totals["chickens"] += loss.quantity
            total_chickens_lost += loss.quantity

        movements = await chicken_movement_service.list_movements(
            farm,
            from_date=from_date,
            to_date=to_date,
        )
        if block_id is None:
            movement_summary = {
                "movement_count": len(movements),
                "chickens_moved": sum(item.quantity for item in movements),
            }
        else:
            inbound = [
                item for item in movements if item.to_block_id == block_id
            ]
            outbound = [
                item for item in movements if item.from_block_id == block_id
            ]
            movement_summary = {
                "movement_count": len(inbound) + len(outbound),
                "chickens_moved_in": sum(item.quantity for item in inbound),
                "chickens_moved_out": sum(item.quantity for item in outbound),
            }

        consumption = await product_consumption_service.list_consumptions(
            farm,
            block_id=block_id,
            from_date=from_date,
            to_date=to_date,
        )
        consumption_totals: dict[UUID, Decimal] = {}
        for item in consumption:
            consumption_totals[item.product_id] = (
                consumption_totals.get(item.product_id, Decimal("0"))
                + item.quantity_in_base_unit
            )

        def summarize_products(
            totals: dict[UUID, Decimal],
        ) -> dict[str, Any]:
            missing_product_ids = set(totals).difference(product_details)
            if missing_product_ids:
                raise AppError(
                    "AI_ASSISTANT_DATA_INCONSISTENT",
                    "The operations summary contains unavailable products.",
                    500,
                )
            products_without_base_units = [
                product_id
                for product_id in totals
                if product_details[product_id][2] is None
                or product_details[product_id][3] is None
            ]
            if products_without_base_units:
                raise AppError(
                    "AI_ASSISTANT_DATA_INCONSISTENT",
                    "The operations summary contains products with unavailable units.",
                    500,
                )
            products_summary = [
                {
                    "product_name": product_details[product_id][0],
                    "product_type": product_details[product_id][1],
                    "quantity": format(quantity, "f"),
                    "unit_name": product_details[product_id][2],
                    "unit_abbreviation": product_details[product_id][3],
                }
                for product_id, quantity in sorted(
                    totals.items(),
                    key=lambda entry: product_details[entry[0]][0].casefold(),
                )
            ]
            return {
                "product_count": len(products_summary),
                "products_truncated": len(products_summary) > 100,
                "by_product": products_summary[:100],
            }

        summary: dict[str, Any] = {
            "period": {
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
            },
            "scope": {
                "type": "block" if block_id is not None else "farm",
                "block_name": block_name,
            },
            "egg_collections": {
                "record_count": collection_count,
                **summarize_products(collection_totals),
            },
            "chicken_losses": {
                "record_count": len(chicken_losses),
                "chickens_lost": total_chickens_lost,
                "by_reason": [
                    {"reason": reason, **totals}
                    for reason, totals in sorted(chicken_loss_reasons.items())
                ],
            },
            "chicken_movements": movement_summary,
            "product_consumption": {
                "record_count": len(consumption),
                **summarize_products(consumption_totals),
            },
        }

        if block_id is None:
            egg_losses = await egg_loss_service.list_losses(
                farm,
                from_date=from_date,
                to_date=to_date,
            )
            egg_loss_totals: dict[UUID, Decimal] = {}
            for loss in egg_losses:
                egg_loss_totals[loss.product_id] = (
                    egg_loss_totals.get(loss.product_id, Decimal("0"))
                    + loss.quantity_in_base_unit
                )
            summary["egg_losses"] = {
                "attribution": "farm",
                "record_count": len(egg_losses),
                **summarize_products(egg_loss_totals),
            }
        else:
            summary["egg_losses"] = {
                "attribution": "not_available_for_block",
                "note": (
                    "Egg loss records are not associated with a block, so "
                    "farm-wide egg losses are excluded from this block summary."
                ),
            }

        return summary
