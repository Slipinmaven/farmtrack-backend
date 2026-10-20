from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

from app.core.config import settings
from app.core.exceptions import FarmLogoTooLargeError, InvalidFarmLogoError

MAX_FARM_LOGO_BYTES = 5 * 1024 * 1024
MAX_FARM_LOGO_MB = 5
_ALLOWED_IMAGE_TYPES = {
    "image/jpeg": (".jpg", lambda content: content.startswith(b"\xff\xd8\xff")),
    "image/png": (".png", lambda content: content.startswith(b"\x89PNG\r\n\x1a\n")),
    "image/webp": (
        ".webp",
        lambda content: len(content) >= 12
        and content[:4] == b"RIFF"
        and content[8:12] == b"WEBP",
    ),
}


class FarmLogoStorage:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or settings.media_directory).resolve()

    def save(self, farm_id: UUID, content_type: str | None, content: bytes) -> str:
        if len(content) > MAX_FARM_LOGO_BYTES:
            raise FarmLogoTooLargeError(MAX_FARM_LOGO_MB)

        image_type = _ALLOWED_IMAGE_TYPES.get((content_type or "").lower())
        if image_type is None or not image_type[1](content):
            raise InvalidFarmLogoError()

        extension = image_type[0]
        filename = f"{uuid4().hex}{extension}"
        farm_directory = self.root / "farm-logos" / str(farm_id)
        farm_directory.mkdir(parents=True, exist_ok=True)
        (farm_directory / filename).write_bytes(content)
        return f"/media/farm-logos/{farm_id}/{filename}"

    def delete(self, logo_path: str | None) -> None:
        if not logo_path:
            return

        parts = PurePosixPath(logo_path).parts
        if (
            len(parts) != 5
            or parts[:3] != ("/", "media", "farm-logos")
            or not parts[3]
            or not parts[4]
        ):
            return

        candidate = (self.root / "farm-logos" / parts[3] / parts[4]).resolve()
        try:
            candidate.relative_to(self.root / "farm-logos")
        except ValueError:
            return

        candidate.unlink(missing_ok=True)
        try:
            candidate.parent.rmdir()
        except OSError:
            pass
