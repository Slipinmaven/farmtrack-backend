from uuid import uuid4

import pytest

from app.core.exceptions import FarmLogoTooLargeError, InvalidFarmLogoError
from app.services.farm_logo_storage import (
    MAX_FARM_LOGO_BYTES,
    FarmLogoStorage,
)


PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def test_save_and_delete_farm_logo(tmp_path):
    farm_id = uuid4()
    storage = FarmLogoStorage(tmp_path)

    logo_path = storage.save(farm_id, "image/png", PNG_HEADER + b"image data")

    assert logo_path.startswith(f"/media/farm-logos/{farm_id}/")
    logo_file = tmp_path / logo_path.removeprefix("/media/")
    assert logo_file.read_bytes() == PNG_HEADER + b"image data"

    storage.delete(logo_path)

    assert not logo_file.exists()
    assert not logo_file.parent.exists()


def test_resolve_is_limited_to_the_farm_and_generated_files(tmp_path):
    farm_id = uuid4()
    other_farm_id = uuid4()
    storage = FarmLogoStorage(tmp_path)
    logo_path = storage.save(farm_id, "image/png", PNG_HEADER + b"image data")

    resolved = storage.resolve(farm_id, logo_path)

    assert resolved is not None
    assert resolved[0].read_bytes() == PNG_HEADER + b"image data"
    assert resolved[1] == "image/png"
    assert storage.resolve(other_farm_id, logo_path) is None
    assert storage.resolve(farm_id, "/media/farm-logos/../../outside.png") is None


def test_rejects_unsupported_and_mislabeled_images(tmp_path):
    storage = FarmLogoStorage(tmp_path)
    farm_id = uuid4()

    with pytest.raises(InvalidFarmLogoError):
        storage.save(farm_id, "image/svg+xml", b"<svg />")

    with pytest.raises(InvalidFarmLogoError):
        storage.save(farm_id, "image/png", b"not a png")


def test_rejects_oversized_image(tmp_path):
    storage = FarmLogoStorage(tmp_path)

    with pytest.raises(FarmLogoTooLargeError):
        storage.save(uuid4(), "image/png", PNG_HEADER + b"x" * MAX_FARM_LOGO_BYTES)


def test_delete_ignores_non_media_and_traversal_paths(tmp_path):
    storage = FarmLogoStorage(tmp_path)
    outside_file = tmp_path / "outside.png"
    outside_file.write_bytes(b"keep")

    storage.delete("https://example.test/logo.png")
    storage.delete("/media/farm-logos/../../outside.png")

    assert outside_file.read_bytes() == b"keep"
