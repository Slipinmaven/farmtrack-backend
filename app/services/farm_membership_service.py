from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import AuthorizationError, ConflictError, ResourceNotFoundError
from app.core.unit_of_work import UnitOfWork
from app.models.farm import Farm
from app.models.farm_membership import FarmMembership
from app.models.user import User
from app.repositories.farm_membership_repository import FarmMembershipRepository
from app.repositories.user_repository import UserRepository
from app.schemas.enums import FarmMembershipStatus, FarmRole
from app.services.auth_service import normalize_email


class FarmMembershipService:
    def __init__(
        self,
        membership_repository: FarmMembershipRepository,
        user_repository: UserRepository,
        unit_of_work: UnitOfWork,
    ):
        self.membership_repository = membership_repository
        self.user_repository = user_repository
        self.unit_of_work = unit_of_work

    async def list_members(self, farm: Farm) -> list[FarmMembership]:
        async with self.unit_of_work:
            return await self.membership_repository.list_by_farm(farm.id)

    async def list_invitations(self, user: User) -> list[FarmMembership]:
        async with self.unit_of_work:
            return await self.membership_repository.list_invitations(user.id)

    async def invite(
        self,
        *,
        farm: Farm,
        actor: User,
        email: str,
        role: FarmRole,
    ) -> FarmMembership:
        if role == FarmRole.OWNER:
            raise ConflictError("Farm ownership cannot be assigned by invitation.")

        try:
            async with self.unit_of_work:
                invited_user = await self.user_repository.get_by_email(
                    normalize_email(email)
                )
                if invited_user is None or not invited_user.is_active:
                    raise ResourceNotFoundError(
                        "An active FarmTrack account with that email was not found."
                    )
                if invited_user.id == farm.owner_id:
                    raise ConflictError("The farm owner is already a member.")
                if actor.id != farm.owner_id and role != FarmRole.WORKER:
                    raise AuthorizationError("Managers can invite workers only.")

                membership = await self.membership_repository.get_by_farm_and_user(
                    farm.id,
                    invited_user.id,
                )
                now = datetime.now(timezone.utc)
                if membership is not None:
                    if membership.status != FarmMembershipStatus.REVOKED:
                        raise ConflictError(
                            "This user already has a farm membership or invitation."
                        )
                    membership.role = role.value
                    membership.status = FarmMembershipStatus.INVITED
                    membership.invited_by_id = actor.id
                    membership.invited_at = now
                    membership.accepted_at = None
                    membership.revoked_at = None
                    await self.membership_repository.update(membership)
                else:
                    membership = await self.membership_repository.create(
                        FarmMembership(
                            farm_id=farm.id,
                            user_id=invited_user.id,
                            role=role.value,
                            status=FarmMembershipStatus.INVITED.value,
                            invited_by_id=actor.id,
                            invited_at=now,
                        )
                    )

                await self.unit_of_work.commit()
                saved_membership = await self.membership_repository.get_by_id_for_update(
                    membership.id
                )
                if saved_membership is None:
                    raise RuntimeError("Farm membership disappeared after being saved.")
                return saved_membership
        except IntegrityError as exc:
            raise ConflictError(
                "This user already has a farm membership or invitation."
            ) from exc

    async def accept_invitation(
        self,
        *,
        membership_id: UUID,
        user: User,
    ) -> FarmMembership:
        async with self.unit_of_work:
            membership = await self.membership_repository.get_by_id_for_update(
                membership_id
            )
            if membership is None or membership.user_id != user.id:
                raise ResourceNotFoundError("Farm invitation not found.")
            if membership.status != FarmMembershipStatus.INVITED:
                raise ConflictError("This farm invitation is no longer pending.")

            membership.status = FarmMembershipStatus.ACTIVE
            membership.accepted_at = datetime.now(timezone.utc)
            await self.membership_repository.update(membership)
            await self.unit_of_work.commit()
            return membership

    async def update_role(
        self,
        *,
        farm: Farm,
        actor: User,
        membership_id: UUID,
        role: FarmRole,
    ) -> FarmMembership:
        if role == FarmRole.OWNER:
            raise ConflictError("Farm ownership cannot be assigned as a member role.")

        async with self.unit_of_work:
            membership = await self._get_farm_membership(farm, membership_id)
            self._ensure_member_management_allowed(farm, actor, membership)
            if actor.id != farm.owner_id and role != FarmRole.WORKER:
                raise AuthorizationError("Managers can assign the worker role only.")
            membership.role = role.value
            await self.membership_repository.update(membership)
            await self.unit_of_work.commit()
            return membership

    async def revoke(
        self,
        *,
        farm: Farm,
        actor: User,
        membership_id: UUID,
    ) -> None:
        async with self.unit_of_work:
            membership = await self._get_farm_membership(farm, membership_id)
            self._ensure_member_management_allowed(farm, actor, membership)
            if membership.status == FarmMembershipStatus.REVOKED:
                raise ConflictError("This farm membership has already been revoked.")
            membership.status = FarmMembershipStatus.REVOKED
            membership.revoked_at = datetime.now(timezone.utc)
            await self.membership_repository.update(membership)
            await self.unit_of_work.commit()

    async def _get_farm_membership(
        self,
        farm: Farm,
        membership_id: UUID,
    ) -> FarmMembership:
        membership = await self.membership_repository.get_by_id_for_update(
            membership_id
        )
        if membership is None or membership.farm_id != farm.id:
            raise ResourceNotFoundError("Farm member not found.")
        return membership

    @staticmethod
    def _ensure_member_management_allowed(
        farm: Farm,
        actor: User,
        membership: FarmMembership,
    ) -> None:
        if membership.user_id == farm.owner_id:
            raise AuthorizationError("The farm owner cannot be removed or reassigned.")
        if actor.id != farm.owner_id and membership.role != FarmRole.WORKER:
            raise AuthorizationError("Managers can manage worker memberships only.")
