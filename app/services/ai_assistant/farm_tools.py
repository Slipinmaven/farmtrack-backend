from typing import Any

from app.core.exceptions import AppError
from app.services.ai_assistant.contracts import AppNavigationToolArguments
from app.services.ai_assistant.service_context import AssistantToolHandlerBase
from app.services.assistant_route_catalog import APP_ROUTE_CATALOG


class FarmToolHandlers(AssistantToolHandlerBase):
    async def _handle_get_app_navigation(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        parsed = AppNavigationToolArguments.model_validate(arguments)
        destination = self.context.service.APP_DESTINATIONS.get(parsed.destination)
        if destination is None:
            return {"error": "Unsupported app destination."}
        self.context.navigation_destination = parsed.destination
        return {
            "destination": parsed.destination,
            **destination,
        }

    async def _handle_get_app_route_catalog(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if arguments:
            return {"error": "This route catalog takes no arguments."}
        return {
            "routes": [
                {
                    "path": route.path,
                    "label": route.label,
                    "purpose": route.purpose,
                    "entry_points": list(route.entry_points),
                }
                for route in APP_ROUTE_CATALOG
            ]
        }

    async def _handle_get_current_farm(
        self,
        _arguments: dict[str, Any],
    ) -> dict[str, Any]:
        del _arguments
        if self.context.farm is None:
            raise AppError(
                "AI_ASSISTANT_UNAVAILABLE",
                "Current farm information is not available.",
                503,
            )
        self.context.data_scopes.append("farm_context")
        return {"farm_name": self.context.service._safe_contact_name(self.context.farm.name)}
