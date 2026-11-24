from typing import Any

from app.core.exceptions import AppError
from app.services.ai_assistant.contracts import (
    BlockStatusToolArguments,
    FarmOperationsSummaryToolArguments,
    InventoryBalancesToolArguments,
)
from app.services.ai_assistant.date_ranges import resolve_tool_date_range
from app.services.ai_assistant.service_context import AssistantToolHandlerBase


class OperationsToolHandlers(AssistantToolHandlerBase):
    async def _handle_get_farm_block_status(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.context.farm is None or self.context.service.block_service is None:
            raise AppError(
                "AI_ASSISTANT_UNAVAILABLE",
                "The block status read tool is not configured.",
                503,
            )
        parsed = BlockStatusToolArguments.model_validate(arguments)
        blocks = await self.context.service.block_service.list_blocks(
            self.context.farm,
            search=parsed.block_name,
        )
        if parsed.block_name is not None:
            matching_blocks = [
                block
                for block in blocks
                if block.name.strip().casefold()
                == parsed.block_name.strip().casefold()
            ]
            if len(matching_blocks) != 1:
                return {
                    "match_status": (
                        "ambiguous" if matching_blocks else "not_found"
                    ),
                    "requested_block": parsed.block_name,
                    "candidate_blocks": [
                        block.name
                        for block in matching_blocks or blocks[:20]
                    ],
                }
            blocks = matching_blocks
        total_occupied = sum(
            block.occupied_chickens for block in blocks
        )
        self.context.data_scopes.append("block_status")
        return {
            "flock_count_scope": "assigned_to_blocks",
            "assigned_chicken_count": total_occupied,
            "block_count": len(blocks),
            "blocks": [
                {
                    "block_name": block.name,
                    "occupied_chickens": block.occupied_chickens,
                    "capacity": block.capacity,
                    "full": (
                        block.capacity > 0
                        and block.occupied_chickens >= block.capacity
                    ),
                    "nearly_full": (
                        block.capacity > 0
                        and block.occupied_chickens
                        >= block.capacity * 0.9
                    ),
                    "occupancy_percent": (
                        round(
                            block.occupied_chickens
                            / block.capacity
                            * 100,
                            1,
                        )
                        if block.capacity > 0
                        else None
                    ),
                }
                for block in blocks[:100]
            ],
            "blocks_truncated": len(blocks) > 100,
        }

    async def _handle_get_farm_operations_summary(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if self.context.farm is None:
            raise AppError(
                "AI_ASSISTANT_UNAVAILABLE",
                "The farm operations read tools are not configured.",
                503,
            )
        parsed = FarmOperationsSummaryToolArguments.model_validate(
            arguments
        )
        from_date, to_date = resolve_tool_date_range(
            parsed,
            self.context.question,
            default_period="month_to_date",
        )
        if from_date is None or to_date is None:
            raise AppError(
                "AI_ASSISTANT_INVALID_DATE_RANGE",
                "A date range could not be resolved.",
                422,
            )
        parsed = parsed.model_copy(
            update={"from_date": from_date, "to_date": to_date}
        )
        result = await self.context.service._farm_operations_summary(self.context.farm, parsed)
        if "period" in result:
            self.context.used_from_date = parsed.from_date
            self.context.used_to_date = parsed.to_date
            self.context.data_scopes.append("farm_operations_summary")
        return result

    async def _handle_get_inventory_balances(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self.context.service.inventory_service is None:
            return {"error": "Inventory read capability is unavailable."}
        parsed = InventoryBalancesToolArguments.model_validate(arguments)
        inventory = await self.context.service.inventory_service.get_balances(self.context.farm_id)
        items = [
            item
            for item in inventory
            if parsed.product_name is None
            or item.product_name.strip().casefold()
            == parsed.product_name.strip().casefold()
        ]
        total_items = len(items)
        items = items[:200]
        self.context.data_scopes.append("inventory_balances")
        return {
            "match_status": (
                "matched" if parsed.product_name else "all_products"
            ),
            "product_count": total_items,
            "products_truncated": total_items > len(items),
            "items": [
                {
                    "product_name": item.product_name,
                    "product_type": item.product_type,
                    "quantity": format(item.quantity, "f"),
                    "unit_name": item.unit_name,
                    "unit_abbreviation": item.unit_abbreviation,
                }
                for item in items
            ],
        }
