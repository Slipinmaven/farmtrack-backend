from uuid import UUID

from fastapi import Depends

from app.core.exceptions import AuthenticationError, AuthorizationError, ResourceNotFoundError
from app.dependencies.auth import get_current_user
from app.dependencies.services import get_farm_repository
from app.models.farm import Farm
from app.models.user import User
from app.repositories.farm_repository import FarmRepository


async def get_owned_farm(
    farm_id: UUID,
    current_user: User = Depends(get_current_user),
    farm_repository: FarmRepository = Depends(get_farm_repository),
) -> Farm:
    if not current_user.is_active:
        raise AuthenticationError()

    farm = await farm_repository.get_by_id(farm_id)
    if farm is None:
        raise ResourceNotFoundError("Farm not found.")
    if farm.owner_id != current_user.id:
        raise AuthorizationError("You do not have access to this farm.")
    return farm