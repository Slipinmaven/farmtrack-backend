from decimal import Decimal

from app.schemas.enums import ThemeMode

DEFAULT_FARM_SETTINGS = {
    "primary_color": "#226B68",
    "secondary_color": "#BF6C52",
    "font_family": "Inter",
    "font_scale": Decimal("1.00"),
    "theme_mode": ThemeMode.SYSTEM,
    "logo_path": None,
    "currency": "KES",
    "timezone": "Africa/Nairobi",
}