import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.schema import Table
from pydantic import SecretStr

from app.core.exceptions import (
    AuthenticationError,
    ConflictError,
    ResourceNotFoundError,
)
from app.core.logging import get_application_logger
from app.core.unit_of_work import UnitOfWork
from app.models.farm import Farm
from app.models.farm_logo_cleanup_job import FarmLogoCleanupJob
from app.models.farm_membership import FarmMembership
from app.models.download_token import DownloadToken
from app.models.notification_outbox import NotificationOutbox
from app.models.reminders import Reminder
from app.models.user import User
from app.repositories.deletion_tree import delete_record_tree
from app.repositories.farm_repository import FarmRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.repositories.user_session_repository import UserSessionRepository
from app.services.farm_logo_storage import FarmLogoStorage
from app.services.email_gateway_service import FarmTrackEmailService
from app.core.security import verify_password

DELETION_GRACE_PERIOD = timedelta(days=30)
logger = get_application_logger()


class DataDeletionService:
    def __init__(
        self,
        *,
        user_repository: UserRepository,
        farm_repository: FarmRepository,
        user_session_repository: UserSessionRepository,
        refresh_token_repository: RefreshTokenRepository,
        unit_of_work: UnitOfWork,
        email_service: FarmTrackEmailService | None = None,
        logo_storage: FarmLogoStorage | None = None,
    ) -> None:
        self.user_repository = user_repository
        self.farm_repository = farm_repository
        self.user_session_repository = user_session_repository
        self.refresh_token_repository = refresh_token_repository
        self.unit_of_work = unit_of_work
        self.email_service = email_service or FarmTrackEmailService()
        self.logo_storage = logo_storage or FarmLogoStorage()

    async def schedule_account_deletion(
        self,
        user_id: UUID,
        current_password: SecretStr,
    ) -> tuple[datetime, bool]:
        now = datetime.now(UTC)
        async with self.unit_of_work:
            user = await self.user_repository.get_by_id_for_update(user_id)
            user = self._verify_user_password(user, current_password)
            if user.deletion_requested_at is not None:
                raise ConflictError("Account deletion has already been scheduled.")
            await self._apply_account_deletion(user, now)
            await self.unit_of_work.commit()

        notification_sent = False
        if self.email_service.is_configured:
            try:
                await self.email_service.send_account_deletion_notice(
                    recipient_email=user.email,
                    scheduled_for=now + DELETION_GRACE_PERIOD,
                )
                notification_sent = True
            except RuntimeError as exc:
                logger.warning(
                    "account_deletion_notice_email_failed",
                    extra={
                        "event": "account_deletion_notice_email_failed",
                        "user_id": user_id,
                        "error_type": type(exc).__name__,
                    },
                )
        else:
            logger.warning(
                "account_deletion_notice_email_not_configured",
                extra={
                    "event": "account_deletion_notice_email_not_configured",
                    "user_id": user_id,
                },
            )

        logger.info(
            "account_deletion_scheduled",
            extra={
                "event": "account_deletion_scheduled",
                "user_id": user_id,
                "deletion_requested_at": now.isoformat(),
                "notification_sent": notification_sent,
            },
        )
        return now + DELETION_GRACE_PERIOD, notification_sent

    async def get_account_deletion_status(self, user_id: UUID) -> dict[str, object]:
        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            raise ResourceNotFoundError("Account not found.")
        now = datetime.now(UTC)
        if user.deletion_requested_at is not None:
            return {
                "status": "scheduled",
                "confirmation_expires_at": None,
                "scheduled_for": self._as_utc(user.deletion_requested_at)
                + DELETION_GRACE_PERIOD,
            }
        if (
            user.deletion_confirmation_token_hash is not None
            and user.deletion_confirmation_expires_at is not None
            and self._as_utc(user.deletion_confirmation_expires_at) > now
        ):
            return {
                "status": "confirmation_pending",
                "confirmation_expires_at": self._as_utc(
                    user.deletion_confirmation_expires_at
                ),
                "scheduled_for": None,
            }
        return {
            "status": "none",
            "confirmation_expires_at": None,
            "scheduled_for": None,
        }

    async def confirm_account_deletion(self, token: str) -> datetime:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        async with self.unit_of_work:
            user = (
                await self.user_repository.get_by_deletion_confirmation_hash_for_update(
                    token_hash
                )
            )
            now = datetime.now(UTC)
            if (
                user is None
                or user.deletion_confirmation_expires_at is None
                or self._as_utc(user.deletion_confirmation_expires_at) <= now
                or user.deletion_requested_at is not None
            ):
                raise ConflictError(
                    "This deletion confirmation link is invalid or has expired."
                )
            await self._apply_account_deletion(user, now)
            await self.unit_of_work.commit()

        logger.info(
            "account_deletion_confirmed",
            extra={
                "event": "account_deletion_confirmed",
                "user_id": user.id,
                "deletion_requested_at": now.isoformat(),
            },
        )
        return now + DELETION_GRACE_PERIOD

    async def cancel_account_deletion(
        self,
        user_id: UUID,
        current_password: SecretStr,
    ) -> None:
        async with self.unit_of_work:
            user = await self.user_repository.get_by_id_for_update(user_id)
            user = self._verify_user_password(user, current_password)
            if (
                user.deletion_requested_at is None
                and user.deletion_confirmation_token_hash is None
            ):
                raise ConflictError("There is no account deletion request to cancel.")
            if (
                user.deletion_requested_at is not None
                and self._as_utc(user.deletion_requested_at)
                <= datetime.now(UTC) - DELETION_GRACE_PERIOD
            ):
                raise ConflictError("The account recovery period has expired.")
            await self._restore_account_data(user)
            await self.unit_of_work.commit()

        notification_sent = await self._send_account_restored_notice(
            user.email,
            user_id,
        )
        logger.info(
            "account_deletion_cancelled",
            extra={
                "event": "account_deletion_cancelled",
                "user_id": user_id,
                "notification_sent": notification_sent,
            },
        )

    async def schedule_farm_deletion(
        self,
        *,
        farm_id: UUID,
        owner_id: UUID,
        current_password: SecretStr,
    ) -> tuple[datetime, bool]:
        async with self.unit_of_work:
            user = await self.user_repository.get_by_id_for_update(owner_id)
            user = self._verify_user_password(user, current_password)
            farm = await self.farm_repository.get_by_owner_and_id_for_update(
                farm_id,
                owner_id,
            )
            if farm is None:
                raise ResourceNotFoundError("Farm not found.")
            if farm.deletion_requested_at is not None:
                raise ConflictError("Farm deletion has already been scheduled.")
            now = datetime.now(UTC)
            farm.deletion_requested_at = now
            await self.unit_of_work.commit()

        notification_sent = False
        if self.email_service.is_configured:
            try:
                await self.email_service.send_farm_deletion_notice(
                    recipient_email=user.email,
                    farm_name=farm.name,
                    scheduled_for=now + DELETION_GRACE_PERIOD,
                )
                notification_sent = True
            except RuntimeError as exc:
                logger.warning(
                    "farm_deletion_notice_email_failed",
                    extra={
                        "event": "farm_deletion_notice_email_failed",
                        "user_id": owner_id,
                        "farm_id": farm_id,
                        "error_type": type(exc).__name__,
                    },
                )
        else:
            logger.warning(
                "farm_deletion_notice_email_not_configured",
                extra={
                    "event": "farm_deletion_notice_email_not_configured",
                    "user_id": owner_id,
                    "farm_id": farm_id,
                },
            )

        logger.info(
            "farm_deletion_scheduled",
            extra={
                "event": "farm_deletion_scheduled",
                "user_id": owner_id,
                "farm_id": farm_id,
                "deletion_requested_at": now.isoformat(),
                "notification_sent": notification_sent,
            },
        )
        return now + DELETION_GRACE_PERIOD, notification_sent

    async def leave_farm(
        self,
        *,
        farm_id: UUID,
        user_id: UUID,
        current_password: SecretStr,
    ) -> dict[str, bool]:
        async with self.unit_of_work:
            user = await self.user_repository.get_by_id_for_update(user_id)
            user = self._verify_user_password(user, current_password)
            farm = await self.farm_repository.get_by_id_for_update(farm_id)
            if farm is None or farm.deletion_requested_at is not None:
                raise ResourceNotFoundError("Farm not found.")
            if farm.owner_id == user_id:
                raise ConflictError("Farm owners must schedule farm deletion instead.")

            membership = await self.farm_repository.get_membership(farm_id, user_id)
            if membership is None or membership.status != "active":
                raise ResourceNotFoundError("Active farm membership not found.")
            owner = await self.user_repository.get_by_id(farm.owner_id)
            farm_name = farm.name
            member_email = user.email
            owner_email = owner.email if owner is not None else None
            membership.status = "revoked"
            membership.revoked_at = datetime.now(UTC)
            await self.unit_of_work.commit()

        email_status = {
            "member_email_sent": False,
            "owner_email_sent": False,
        }
        if self.email_service.is_configured:
            if owner_email is not None:
                try:
                    await self.email_service.send_farm_member_left_notice(
                        recipient_email=owner_email,
                        farm_name=farm_name,
                        member_email=member_email,
                    )
                    email_status["owner_email_sent"] = True
                except RuntimeError as exc:
                    logger.warning(
                        "farm_leave_owner_email_failed",
                        extra={
                            "event": "farm_leave_owner_email_failed",
                            "user_id": user_id,
                            "farm_id": farm_id,
                            "error_type": type(exc).__name__,
                        },
                    )
            else:
                logger.warning(
                    "farm_leave_owner_email_unavailable",
                    extra={
                        "event": "farm_leave_owner_email_unavailable",
                        "user_id": user_id,
                        "farm_id": farm_id,
                    },
                )

            try:
                await self.email_service.send_farm_left_confirmation(
                    recipient_email=member_email,
                    farm_name=farm_name,
                    owner_notified=email_status["owner_email_sent"],
                )
                email_status["member_email_sent"] = True
            except RuntimeError as exc:
                logger.warning(
                    "farm_leave_member_email_failed",
                    extra={
                        "event": "farm_leave_member_email_failed",
                        "user_id": user_id,
                        "farm_id": farm_id,
                        "error_type": type(exc).__name__,
                    },
                )
        else:
            for recipient in ("member", "owner"):
                logger.warning(
                    f"farm_leave_{recipient}_email_not_configured",
                    extra={
                        "event": f"farm_leave_{recipient}_email_not_configured",
                        "user_id": user_id,
                        "farm_id": farm_id,
                    },
                )

        logger.info(
            "farm_membership_left",
            extra={
                "event": "farm_membership_left",
                "user_id": user_id,
                "farm_id": farm_id,
                **email_status,
            },
        )
        return email_status

    async def list_pending_farm_deletions(
        self,
        owner_id: UUID,
    ) -> list[Farm]:
        return await self.farm_repository.list_pending_deletions_for_owner(owner_id)

    async def restore_farm(
        self,
        *,
        farm_id: UUID,
        owner_id: UUID,
        current_password: SecretStr,
    ) -> None:
        async with self.unit_of_work:
            user = await self.user_repository.get_by_id_for_update(owner_id)
            user = self._verify_user_password(user, current_password)
            farm = await self.farm_repository.get_by_owner_and_id_for_update(
                farm_id,
                owner_id,
            )
            if farm is None or farm.deletion_requested_at is None:
                raise ResourceNotFoundError("Scheduled farm deletion not found.")
            if farm.deletion_requested_at <= datetime.now(UTC) - DELETION_GRACE_PERIOD:
                raise ConflictError("The farm recovery period has expired.")
            farm.deletion_requested_at = None
            await self.unit_of_work.commit()

        logger.info(
            "farm_deletion_cancelled",
            extra={
                "event": "farm_deletion_cancelled",
                "user_id": owner_id,
                "farm_id": farm_id,
            },
        )

    async def restore_account(
        self,
        *,
        email: str,
        password: SecretStr,
    ) -> None:
        async with self.unit_of_work:
            user = await self.user_repository.get_by_email_for_update(
                email.strip().lower()
            )
            user = self._verify_user_password(user, password)
            if (
                user.deletion_requested_at is None
                and user.deletion_confirmation_token_hash is None
            ):
                raise ConflictError("There is no account deletion request to cancel.")
            if (
                user.deletion_requested_at is not None
                and self._as_utc(user.deletion_requested_at)
                <= datetime.now(UTC) - DELETION_GRACE_PERIOD
            ):
                raise ConflictError("The account recovery period has expired.")
            await self._restore_account_data(user)
            await self.unit_of_work.commit()

        notification_sent = await self._send_account_restored_notice(
            user.email,
            user.id,
        )
        logger.info(
            "account_deletion_cancelled",
            extra={
                "event": "account_deletion_cancelled",
                "user_id": user.id,
                "notification_sent": notification_sent,
            },
        )

    async def _send_account_restored_notice(
        self,
        recipient_email: str,
        user_id: UUID,
    ) -> bool:
        if not self.email_service.is_configured:
            logger.warning(
                "account_restored_notice_email_not_configured",
                extra={
                    "event": "account_restored_notice_email_not_configured",
                    "user_id": user_id,
                },
            )
            return False
        try:
            await self.email_service.send_account_restored_notice(
                recipient_email=recipient_email,
            )
        except RuntimeError as exc:
            logger.warning(
                "account_restored_notice_email_failed",
                extra={
                    "event": "account_restored_notice_email_failed",
                    "user_id": user_id,
                    "error_type": type(exc).__name__,
                },
            )
            return False
        return True

    @staticmethod
    async def process_expired_deletions(
        session: AsyncSession,
        logo_storage: FarmLogoStorage | None = None,
    ) -> tuple[int, int]:
        now = datetime.now(UTC)
        cutoff = now - DELETION_GRACE_PERIOD
        storage = logo_storage or FarmLogoStorage()
        deleted_user_count = 0
        deleted_farm_count = 0
        async with session.begin():
            await session.execute(
                delete(DownloadToken).where(
                    or_(
                        DownloadToken.expires_at <= now,
                        DownloadToken.revoked_at <= now,
                    )
                )
            )
            users = list(
                (
                    await session.scalars(
                        select(User)
                        .where(User.deletion_requested_at <= cutoff)
                        .order_by(User.deletion_requested_at, User.id)
                        .limit(100)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            user_ids = {user.id for user in users}
            farm_query = (
                select(Farm)
                .options(selectinload(Farm.farm_settings))
                .where(Farm.deletion_requested_at <= cutoff)
            )
            if user_ids:
                farm_query = farm_query.where(Farm.owner_id.not_in(user_ids))
            farms = list(
                (
                    await session.scalars(
                        farm_query.order_by(Farm.deletion_requested_at, Farm.id)
                        .limit(100)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            account_farms = list(
                (
                    await session.scalars(
                        select(Farm)
                        .options(selectinload(Farm.farm_settings))
                        .where(Farm.owner_id.in_(user_ids))
                    )
                ).all()
            ) if user_ids else []
            for user in users:
                owned_farms = [farm for farm in account_farms if farm.owner_id == user.id]
                try:
                    async with session.begin_nested():
                        await DataDeletionService._scrub_user_specific_records(
                            session,
                            user,
                            now,
                        )
                        await session.execute(
                            delete(DownloadToken).where(
                                func.lower(DownloadToken.recipient_email)
                                == user.email.lower()
                            )
                        )
                        for farm in owned_farms:
                            await DataDeletionService._enqueue_logo_cleanup(
                                session,
                                farm,
                            )
                            await delete_record_tree(
                                session,
                                cast(Table, Farm.__table__),
                                farm.id,
                            )
                        await delete_record_tree(
                            session,
                            cast(Table, User.__table__),
                            user.id,
                        )
                    deleted_user_count += 1
                    deleted_farm_count += len(owned_farms)
                except Exception:
                    logger.exception(
                        "scheduled_account_deletion_failed",
                        extra={
                            "event": "scheduled_account_deletion_failed",
                            "user_id": user.id,
                        },
                    )

            for farm in farms:
                try:
                    async with session.begin_nested():
                        await DataDeletionService._enqueue_logo_cleanup(session, farm)
                        await delete_record_tree(
                            session,
                            cast(Table, Farm.__table__),
                            farm.id,
                        )
                    deleted_farm_count += 1
                except Exception:
                    logger.exception(
                        "scheduled_farm_deletion_failed",
                        extra={
                            "event": "scheduled_farm_deletion_failed",
                            "farm_id": farm.id,
                        },
                    )

        await DataDeletionService.process_pending_logo_cleanup(session, storage, now)
        return deleted_user_count, deleted_farm_count

    @staticmethod
    async def process_pending_logo_cleanup(
        session: AsyncSession,
        storage: FarmLogoStorage,
        now: datetime | None = None,
    ) -> int:
        current_time = now or datetime.now(UTC)
        completed = 0
        async with session.begin():
            jobs = list(
                (
                    await session.scalars(
                        select(FarmLogoCleanupJob)
                        .where(FarmLogoCleanupJob.available_at <= current_time)
                        .order_by(
                            FarmLogoCleanupJob.available_at,
                            FarmLogoCleanupJob.created_at,
                            FarmLogoCleanupJob.id,
                        )
                        .limit(100)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            for job in jobs:
                try:
                    await asyncio.to_thread(storage.delete, job.logo_path)
                except OSError as exc:
                    job.attempts += 1
                    job.available_at = current_time + timedelta(
                        seconds=min(2 ** min(job.attempts, 12), 3600)
                    )
                    job.last_error_type = type(exc).__name__
                    logger.warning(
                        "scheduled_deletion_logo_cleanup_failed",
                        extra={
                            "event": "scheduled_deletion_logo_cleanup_failed",
                            "cleanup_job_id": job.id,
                            "error_type": type(exc).__name__,
                            "attempt": job.attempts,
                        },
                    )
                else:
                    await session.delete(job)
                    completed += 1
        return completed

    @staticmethod
    async def _enqueue_logo_cleanup(
        session: AsyncSession,
        farm: Farm,
    ) -> None:
        farm_settings = farm.farm_settings
        if farm_settings is not None and farm_settings.logo_path:
            session.add(FarmLogoCleanupJob(logo_path=farm_settings.logo_path))

    @staticmethod
    async def _scrub_user_specific_records(
        session: AsyncSession,
        user: User,
        now: datetime,
    ) -> None:
        reminders = list(
            (
                await session.scalars(
                    select(Reminder)
                    .where(Reminder.created_by_user_id == user.id)
                    .with_for_update()
                )
            ).all()
        )
        for reminder in reminders:
            reminder.expo_push_token = None
            reminder.delivery_channel = "in_app"

        outbox_events = list(
            (
                await session.scalars(
                    select(NotificationOutbox)
                    .where(NotificationOutbox.created_by_user_id == user.id)
                    .with_for_update()
                )
            ).all()
        )
        for event in outbox_events:
            payload = dict(event.payload)
            payload.pop("expo_push_token", None)
            event.payload = payload
            if (
                event.event_type == "reminder.push"
                and event.processed_at is None
                and event.failed_at is None
            ):
                event.processed_at = now
                event.last_error = None

    async def _apply_account_deletion(self, user: User, now: datetime) -> None:
        user.deletion_requested_at = now
        user.deletion_confirmation_token_hash = None
        user.deletion_confirmation_expires_at = None

        for farm in await self.farm_repository.list_owned_for_update(user.id):
            if farm.deletion_requested_at is None:
                farm.deletion_requested_at = now

        for membership in await self.farm_repository.list_memberships_for_user_for_update(
            user.id
        ):
            if (
                membership.status in {"active", "invited"}
                and membership.account_deletion_at is None
            ):
                membership.account_deletion_previous_status = membership.status
                membership.account_deletion_at = now
                membership.status = "revoked"
                membership.revoked_at = now

        await self.user_session_repository.revoke_for_user(
            user.id,
            now,
            "account_deletion",
        )
        await self.refresh_token_repository.revoke_for_user(user.id, now)

    @staticmethod
    def _verify_user_password(
        user: User | None,
        password: SecretStr,
    ) -> User:
        if user is None or not verify_password(
            password.get_secret_value(),
            user.password_hash,
        ):
            raise AuthenticationError("Invalid email or password.")
        return user

    async def _restore_account_data(self, user: User) -> None:
        deletion_at = user.deletion_requested_at
        user.deletion_requested_at = None
        user.deletion_confirmation_token_hash = None
        user.deletion_confirmation_expires_at = None
        if deletion_at is None:
            return

        farms = await self.unit_of_work.session.scalars(
            select(Farm).where(
                Farm.owner_id == user.id,
                Farm.deletion_requested_at == deletion_at,
            )
        )
        for farm in farms:
            farm.deletion_requested_at = None

        memberships = await self.unit_of_work.session.scalars(
            select(FarmMembership).where(
                FarmMembership.user_id == user.id,
                FarmMembership.account_deletion_at == deletion_at,
            )
        )
        for membership in memberships:
            membership.status = (
                membership.account_deletion_previous_status or "active"
            )
            membership.revoked_at = None
            membership.account_deletion_at = None
            membership.account_deletion_previous_status = None

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
