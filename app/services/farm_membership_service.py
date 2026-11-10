from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import AuthorizationError, ConflictError, ResourceNotFoundError
from app.core.logging import get_application_logger
from app.core.security import hash_password_async
from app.core.unit_of_work import UnitOfWork
from app.models.app_security_settings import AppSecuritySettings
from app.models.farm import Farm
from app.models.farm_membership import FarmMembership
from app.models.user import User
from app.repositories.farm_membership_repository import FarmMembershipRepository
from app.repositories.notification_outbox_repository import NotificationOutboxRepository
from app.repositories.user_repository import UserRepository
from app.schemas.enums import FarmInvitationEmailStatus, FarmMembershipStatus, FarmRole
from app.services.auth_service import normalize_email
from app.services.smtp_email_service import SMTPEmailService

logger = get_application_logger()


class FarmMembershipService:
    def __init__(
        self,
        membership_repository: FarmMembershipRepository,
        user_repository: UserRepository,
        unit_of_work: UnitOfWork,
        notification_outbox_repository: NotificationOutboxRepository | None = None,
        email_service: SMTPEmailService | None = None,
    ):
        self.membership_repository = membership_repository
        self.user_repository = user_repository
        self.unit_of_work = unit_of_work
        self.notification_outbox_repository = notification_outbox_repository
        self.email_service = email_service or SMTPEmailService()

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
        create_account: bool = False,
        initial_password: str | None = None,
    ) -> FarmMembership:
        if role == FarmRole.OWNER:
            raise ConflictError("Farm ownership cannot be assigned by invitation.")
        if create_account and actor.id != farm.owner_id:
            raise AuthorizationError("Only the farm owner can create a user account.")
        if create_account and (
            initial_password is None or len(initial_password) < 8
        ):
            raise ConflictError(
                "A new account requires an initial password of at least 8 characters."
            )

        try:
            async with self.unit_of_work:
                invited_user = await self.user_repository.get_by_email(
                    normalize_email(email)
                )
                if create_account and invited_user is not None:
                    raise ConflictError(
                        "An account with this email already exists. Invite the existing account instead."
                    )
                if invited_user is None and create_account:
                    invited_user = User(
                        email=normalize_email(email),
                        password_hash=await hash_password_async(initial_password),
                        app_security_setting=AppSecuritySettings(),
                    )
                    await self.user_repository.create(invited_user)
                if invited_user is None or not invited_user.is_active:
                    raise ResourceNotFoundError(
                        "An active FarmTrack account with that email was not found. Choose create account to add a new user."
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
                    membership.invitation_email_sent_at = None
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

                await self._send_or_enqueue_invitation_email(
                    membership,
                    farm_name=farm.name,
                    recipient_email=invited_user.email,
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

    async def resend_invitation(
        self,
        *,
        farm: Farm,
        actor: User,
        membership_id: UUID,
    ) -> FarmMembership:
        async with self.unit_of_work:
            membership = await self._get_farm_membership(farm, membership_id)
            self._ensure_member_management_allowed(farm, actor, membership)
            if membership.status != FarmMembershipStatus.INVITED:
                raise ConflictError("Only a pending farm invitation can be resent.")
            if actor.id != farm.owner_id and membership.role != FarmRole.WORKER:
                raise AuthorizationError("Managers can resend worker invitations only.")

            membership.invitation_email_sent_at = None
            await self._send_or_enqueue_invitation_email(
                membership,
                farm_name=farm.name,
                recipient_email=membership.user.email,
            )
            await self.membership_repository.update(membership)
            await self.unit_of_work.commit()
            return membership

    async def _send_or_enqueue_invitation_email(
        self,
        membership: FarmMembership,
        *,
        farm_name: str,
        recipient_email: str,
    ) -> None:
        if not self.email_service.is_configured:
            membership.invitation_email_status = (
                FarmInvitationEmailStatus.NOT_CONFIGURED.value
            )
            return

        try:
            await self.email_service.send_farm_invitation(
                membership=membership,
                idempotency_key=uuid4(),
                farm_name=farm_name,
                recipient_email=recipient_email,
            )
        except Exception as exc:
            logger.warning(
                "Direct farm invitation email delivery failed; queuing a retry.",
                extra={
                    "event": "farm_invitation_email_queued_after_direct_failure",
                    "farm_id": str(membership.farm_id),
                    "membership_id": str(membership.id),
                    "error_type": type(exc).__name__,
                },
            )
            await self._enqueue_invitation_email(membership)
            return

        membership.invitation_email_status = FarmInvitationEmailStatus.SENT.value
        membership.invitation_email_sent_at = datetime.now(timezone.utc)

    async def _enqueue_invitation_email(self, membership: FarmMembership) -> None:
        if self.notification_outbox_repository is None:
            raise RuntimeError(
                "The invitation email outbox repository is not configured."
            )

        membership.invitation_email_status = FarmInvitationEmailStatus.QUEUED.value
        await self.notification_outbox_repository.enqueue(
            farm_id=membership.farm_id,
            event_type="farm.invitation.email",
            payload={"membership_id": str(membership.id)},
            dedupe_key=f"farm-invitation:{membership.id}:{uuid4()}",
        )

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
            if membership.invitation_email_status == FarmInvitationEmailStatus.QUEUED:
                membership.invitation_email_status = (
                    FarmInvitationEmailStatus.CANCELLED.value
                )
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
