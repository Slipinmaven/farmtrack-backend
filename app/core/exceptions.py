from dataclasses import dataclass
from uuid import UUID

@dataclass
class AppError(Exception):
    code: str
    message: str
    status_code: int = 400


class DatabaseConnectionError(AppError):
    def __init__(self, message: str = "The database is unavailable."):
        super().__init__("DATABASE_UNAVAILABLE", message, 503)


class AuthenticationError(AppError):
    def __init__(self, message: str = "Authentication failed."):
        super().__init__("AUTHENTICATION_FAILED", message, 401)


class DeviceBlockedError(AppError):
    def __init__(self, message: str = "This device is blocked from signing in."):
        super().__init__("DEVICE_BLOCKED", message, 403)


class AuthorizationError(AppError):
    def __init__(self, message: str = "You are not authorized to perform this action."):
        super().__init__("AUTHORIZATION_FAILED", message, 403)


class ResourceNotFoundError(AppError):
    def __init__(self, message: str = "The requested resource was not found."):
        super().__init__("RESOURCE_NOT_FOUND", message, 404)


class ConflictError(AppError):
    def __init__(self, message: str = "The request conflicts with existing data."):
        super().__init__("CONFLICT", message, 409)


class InvalidFarmLogoError(AppError):
    def __init__(self, message: str = "Choose a valid PNG, JPEG, or WebP image."):
        super().__init__("INVALID_FARM_LOGO", message, 415)


class FarmLogoTooLargeError(AppError):
    def __init__(self, maximum_size_mb: int):
        super().__init__(
            "FARM_LOGO_TOO_LARGE",
            f"Farm logos must be {maximum_size_mb} MB or smaller.",
            413,
        )


class InvalidActivityCursorError(AppError):
    def __init__(self):
        super().__init__("INVALID_ACTIVITY_CURSOR", "The activity cursor is invalid.", 422)


class InvalidNotificationCursorError(AppError):
    def __init__(self):
        super().__init__("INVALID_NOTIFICATION_CURSOR", "The notification cursor is invalid.", 422)


class FarmSettingsNotFoundError(ResourceNotFoundError):
    def __init__(self, farm_id: UUID):
        message = f"Farm settings for farm_id '{farm_id}' not found."
        super().__init__(message)