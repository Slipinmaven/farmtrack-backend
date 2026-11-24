from datetime import UTC, datetime, timedelta
from uuid import UUID
from pydantic import SecretStr

from app.core.logging import  get_security_logger
from app.core.unit_of_work import UnitOfWork
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_device_id,
    hash_password_async,
    hash_refresh_token,
    verify_password,
)
from app.core.config import settings
from app.core.exceptions import (
    AccountDeletionPendingError,
    AuthenticationError,
    ConflictError,
    DeviceBlockedError,
)
from app.models.app_security_settings import AppSecuritySettings
from app.models.refresh_token import RefreshToken
from app.models.blocked_device import BlockedDevice
from app.models.user_session import UserSession
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_session_repository import UserSessionRepository
from app.schemas.auth import (
    AuthenticationResponse,
    BlockedDeviceResponse,
    SessionHistoryResponse,
    UserResponse,
    UserSessionResponse,
)
from app.schemas.enums import UserRole


security_logger = get_security_logger()

def normalize_email(email: str) -> str:
    return email.strip().lower()

class AuthService:
    def __init__(
        self,
        user_repository: UserRepository,
        refresh_token_repository: RefreshTokenRepository,
        user_session_repository: UserSessionRepository,
        unit_of_work: UnitOfWork,
    ):
        self.user_repository = user_repository
        self.refresh_token_repository = refresh_token_repository
        self.unit_of_work = unit_of_work
        self.user_session_repository = user_session_repository

    async def create_user(self, email: str, password: str) -> User:
        normalized_email = normalize_email(email)  
        async with self.unit_of_work:
            existing_user = await self.user_repository.get_by_email(normalized_email)
            if existing_user:
                security_logger.warning(
                    "user_creation_conflict",
                    extra={"event": "user_creation_conflict"},
                )
                raise ConflictError("An account with this email already exists.")
            
            password_hash = await hash_password_async(password)
            new_user = User(
                email=normalized_email, 
                password_hash=password_hash,
                role=UserRole.USER.value,
                app_security_setting=AppSecuritySettings(),
            )
            await self.user_repository.create(new_user)
            await self.unit_of_work.commit()

            return new_user

    async def login_user(
        self,
        email: str,
        password: SecretStr,
        device_id: str,
        device_name: str | None = None,
        platform: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuthenticationResponse:
        normalized_email = normalize_email(email)
        async with self.unit_of_work:
            user = await self.user_repository.get_by_email(normalized_email)
            if not user:
                security_logger.warning(f"Login attempt with non-existent email: {normalized_email}")
                raise AuthenticationError("Invalid email or password.")
            if not verify_password(password.get_secret_value(), user.password_hash):
                security_logger.warning(f"Invalid password attempt for email: {normalized_email}")
                raise AuthenticationError("Invalid email or password.")
            if not user.is_active:
                raise AuthenticationError("Invalid email or password.")
            if user.deletion_requested_at is not None:
                raise AccountDeletionPendingError()

            now = datetime.now(UTC)
            device_key = hash_device_id(device_id)
            blocked_device = await self.user_session_repository.get_device_block(
                user.id,
                device_key,
            )
            if blocked_device and self._is_block_active(blocked_device, now):
                raise DeviceBlockedError(
                    "This device is blocked from signing in. Contact your account administrator."
                )
            user_session = await self.user_session_repository.create(
                UserSession(
                    user_id=user.id,
                    device_key=device_key,
                    device_name=(device_name or "Unknown device").strip()[:160],
                    platform=(platform or "Unknown platform").strip()[:80],
                    ip_address=ip_address,
                    user_agent=(user_agent or "")[:512] or None,
                    created_at=now,
                    last_seen_at=now,
                )
            )
            session_id = user_session.id

            raw_refresh_token = create_refresh_token()
            refresh_token = RefreshToken(
                user_id=user.id,
                session_id=session_id,
                token_hash=hash_refresh_token(raw_refresh_token),
                created_at=now,
                expires_at=now + timedelta(days=settings.refresh_token_expire_days)  
            )
            user.last_login_at = now
            await self.refresh_token_repository.create(refresh_token)
            await self.unit_of_work.commit()
            security_logger.info(
                "authentication_succeeded",
                extra={"event": "authentication_succeeded", "user_id": user.id},
            )

            return self._authentication_response(
                user,
                raw_refresh_token,
                session_id=session_id,
            )
            

    async def refresh(
        self,
        raw_refresh_token: SecretStr,
        device_id: str | None = None,
        device_name: str | None = None,
        platform: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuthenticationResponse:
        now = datetime.now(UTC)
        old_token = await self.refresh_token_repository.get_by_hash(hash_refresh_token(raw_refresh_token.get_secret_value()))
        if old_token is None:
            security_logger.warning(
                "refresh_token_rejected",
                extra={"event": "refresh_token_rejected"},
            )
            raise AuthenticationError("Invalid refresh token.")
        if old_token.revoked_at is not None:
            user = await self.user_repository.get_by_id(old_token.user_id)
            if user is not None and user.deletion_requested_at is not None:
                raise AccountDeletionPendingError()
            security_logger.warning(
                "refresh_token_rejected",
                extra={"event": "refresh_token_rejected", "user_id": old_token.user_id},
            )
            raise AuthenticationError("Invalid refresh token.")
        if self._is_expired(old_token.expires_at, now):
            security_logger.warning(
                "refresh_token_rejected",
                extra={"event": "refresh_token_rejected", "user_id": old_token.user_id},
            )
            raise AuthenticationError("Invalid refresh token.")

        user = await self.user_repository.get_by_id(old_token.user_id)
        if (
            user is None
            or not user.is_active
        ):
            security_logger.warning(
                "refresh_token_rejected",
                extra={"event": "refresh_token_rejected", "user_id": old_token.user_id},
            )
            raise AuthenticationError("Invalid refresh token.")
        if user.deletion_requested_at is not None:
            raise AccountDeletionPendingError()

        user_session = None
        if old_token.session_id is None:
            if not device_id:
                raise AuthenticationError(
                    "Sign in again to register this device securely."
                )
            device_key = hash_device_id(device_id)
            blocked_device = await self.user_session_repository.get_device_block(
                user.id,
                device_key,
            )
            if blocked_device and self._is_block_active(blocked_device, now):
                raise DeviceBlockedError(
                    "This device is blocked from signing in. Contact your account administrator."
                )
            user_session = await self.user_session_repository.create(
                UserSession(
                    user_id=user.id,
                    device_key=device_key,
                    device_name=(device_name or "Unknown device").strip()[:160],
                    platform=(platform or "Unknown platform").strip()[:80],
                    ip_address=ip_address,
                    user_agent=(user_agent or "")[:512] or None,
                    created_at=now,
                    last_seen_at=now,
                )
            )
            old_token.session_id = user_session.id
        else:
            user_session = await self.user_session_repository.get_by_id(
                old_token.session_id
            )
            if (
                user_session is None
                or user_session.user_id != old_token.user_id
                or user_session.revoked_at is not None
            ):
                raise AuthenticationError(
                    "This session is no longer active. Sign in again."
                )
            blocked_device = await self.user_session_repository.get_device_block(
                user_session.user_id,
                user_session.device_key,
            )
            if blocked_device and self._is_block_active(blocked_device, now):
                raise DeviceBlockedError(
                    "This device is blocked from signing in. Contact your account administrator."
                )

        new_raw_token = create_refresh_token()
        new_token = RefreshToken(
            user_id=user.id,
            session_id=user_session.id,
            token_hash=hash_refresh_token(new_raw_token),
            expires_at=now + timedelta(days=settings.refresh_token_expire_days),
        )
        await self.refresh_token_repository.create(new_token)
        old_token.revoked_at = now
        old_token.replaced_by_token_id = new_token.id
        await self.user_session_repository.set_last_seen(user_session, now)
        await self.unit_of_work.commit()
        security_logger.info(
            "refresh_token_rotated",
            extra={"event": "refresh_token_rotated", "user_id": user.id},
        )
        return self._authentication_response(
            user,
            new_raw_token,
            session_id=user_session.id,
        )

    async def logout(self, raw_refresh_token: str) -> None:
        token = await self.refresh_token_repository.get_by_hash(hash_refresh_token(raw_refresh_token))
        if token is None:
            security_logger.warning(
                "logout_rejected",
                extra={"event": "logout_rejected"},
            )
            raise AuthenticationError("Invalid refresh token.")
        if token.revoked_at is None:
            revoked_at = datetime.now(UTC)
            token.revoked_at = revoked_at
            if token.session_id:
                user_session = await self.user_session_repository.get_by_id(
                    token.session_id
                )
                if user_session is not None:
                    await self.user_session_repository.revoke(
                        user_session,
                        revoked_at,
                        "signed_out",
                    )
            await self.unit_of_work.commit()
        security_logger.info(
            "logout_completed",
            extra={"event": "logout_completed", "user_id": token.user_id},
        )

    async def get_active_user(self, user_id: UUID, session_id: UUID) -> User:
        user = await self.user_repository.get_by_id(user_id)
        user_session = await self.user_session_repository.get_by_id(session_id)
        if (
            user_session is not None
            and user_session.user_id == user_id
            and user_session.revocation_reason == "device_blocked"
        ):
            blocked_device = await self.user_session_repository.get_device_block(
                user_id,
                user_session.device_key,
            )
            if blocked_device and self._is_block_active(
                blocked_device,
                datetime.now(UTC),
            ):
                raise DeviceBlockedError(
                    "This device is blocked from signing in. Contact your account administrator."
                )

        if (
            user is None
            or not user.is_active
            or user_session is None
            or user_session.user_id != user_id
            or user_session.revoked_at is not None
        ):
            security_logger.warning(
                "authenticated_session_rejected",
                extra={
                    "event": "authenticated_session_rejected",
                    "user_id": user_id,
                    "session_id": session_id,
                },
            )
            raise AuthenticationError("Authentication failed.")
        if user.deletion_requested_at is not None:
            raise AccountDeletionPendingError()

        now = datetime.now(UTC)
        last_seen = user_session.last_seen_at
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=UTC)
        if now - last_seen >= timedelta(minutes=5):
            await self.user_session_repository.set_last_seen(user_session, now)
            await self.unit_of_work.commit()
        return user

    async def list_sessions(
        self,
        user_id: UUID,
        current_session_id: UUID,
        limit: int = 5,
        offset: int = 0,
        status: str = "all",
        search: str | None = None,
    ) -> SessionHistoryResponse:
        sessions, total = await self.user_session_repository.list_for_user(
            user_id,
            limit=limit,
            offset=offset,
            status=status,
            search=search,
        )
        current_session = await self.user_session_repository.get_by_id(
            current_session_id
        )
        blocks = await self.user_session_repository.list_device_blocks(user_id)
        blocks_by_key = {block.device_key: block for block in blocks}
        return SessionHistoryResponse(
            sessions=[
                UserSessionResponse(
                    id=user_session.id,
                    device_name=user_session.device_name,
                    platform=user_session.platform,
                    ip_address=user_session.ip_address,
                    user_agent=user_session.user_agent,
                    created_at=user_session.created_at,
                    last_seen_at=user_session.last_seen_at,
                    revoked_at=user_session.revoked_at,
                    revocation_reason=user_session.revocation_reason,
                    is_current=user_session.id == current_session_id,
                    is_current_device=(
                        current_session is not None
                        and user_session.device_key == current_session.device_key
                    ),
                    device_is_blocked=(
                        user_session.device_key in blocks_by_key
                        and self._is_block_active(
                            blocks_by_key[user_session.device_key],
                            datetime.now(UTC),
                        )
                    ),
                    device_blocked_until=(
                        blocks_by_key[user_session.device_key].blocked_until
                        if user_session.device_key in blocks_by_key
                        else None
                    ),
                    device_blocked_permanently=(
                        blocks_by_key[user_session.device_key].is_permanent
                        if user_session.device_key in blocks_by_key
                        else False
                    ),
                )
                for user_session in sessions
            ],
            blocked_devices=[
                BlockedDeviceResponse(
                    id=block.id,
                    device_name=block.device_name,
                    is_permanent=block.is_permanent,
                    is_active=self._is_block_active(block, datetime.now(UTC)),
                    blocked_until=block.blocked_until,
                    created_at=block.created_at,
                    updated_at=block.updated_at,
                )
                for block in blocks
            ],
            total=total,
            offset=offset,
            limit=limit,
        )

    async def revoke_session(self, user_id: UUID, session_id: UUID) -> None:
        async with self.unit_of_work:
            user_session = await self.user_session_repository.get_by_id(session_id)
            if user_session is None or user_session.user_id != user_id:
                raise AuthenticationError("Session not found.")
            now = datetime.now(UTC)
            await self.user_session_repository.revoke(
                user_session,
                now,
                "terminated_by_user",
            )
            await self.refresh_token_repository.revoke_for_session(session_id, now)
            await self.unit_of_work.commit()

    async def block_session_device(
        self,
        user_id: UUID,
        session_id: UUID,
        permanent: bool,
        duration_days: int | None,
    ) -> BlockedDeviceResponse:
        async with self.unit_of_work:
            user_session = await self.user_session_repository.get_by_id(session_id)
            if user_session is None or user_session.user_id != user_id:
                raise AuthenticationError("Session not found.")

            now = datetime.now(UTC)
            block = await self.user_session_repository.get_device_block(
                user_id,
                user_session.device_key,
            )
            if block is None:
                block = BlockedDevice(
                    user_id=user_id,
                    device_key=user_session.device_key,
                    device_name=user_session.device_name,
                )
            block.device_name = user_session.device_name
            block.is_permanent = permanent
            block.blocked_until = (
                None if permanent else now + timedelta(days=duration_days or 1)
            )
            await self.user_session_repository.save_device_block(block)
            await self.user_session_repository.revoke_for_device(
                user_id,
                user_session.device_key,
                now,
                "device_blocked",
            )
            await self.refresh_token_repository.revoke_for_device(
                user_id,
                user_session.device_key,
                now,
            )
            await self.unit_of_work.commit()
            return BlockedDeviceResponse(
                id=block.id,
                device_name=block.device_name,
                is_permanent=block.is_permanent,
                is_active=self._is_block_active(block, now),
                blocked_until=block.blocked_until,
                created_at=block.created_at,
                updated_at=block.updated_at,
            )

    async def unblock_device(self, user_id: UUID, block_id: UUID) -> None:
        async with self.unit_of_work:
            block = await self.user_session_repository.get_device_block_by_id(
                user_id,
                block_id,
            )
            if block is None:
                raise AuthenticationError("Blocked device not found.")
            await self.user_session_repository.delete_device_block(block)
            await self.unit_of_work.commit()

    async def change_password(
        self,
        user_id: UUID,
        current_session_id: UUID,
        current_password: SecretStr,
        new_password: SecretStr,
    ) -> None:
        async with self.unit_of_work:
            user = await self.user_repository.get_by_id(user_id)
            if user is None or not verify_password(
                current_password.get_secret_value(),
                user.password_hash,
            ):
                raise AuthenticationError("Current password is incorrect.")
            if verify_password(new_password.get_secret_value(), user.password_hash):
                raise ConflictError("Choose a password you have not used before.")

            now = datetime.now(UTC)
            user.password_hash = await hash_password_async(
                new_password.get_secret_value()
            )
            await self.user_session_repository.revoke_for_user(
                user_id,
                now,
                "password_changed",
                except_session_id=current_session_id,
            )
            await self.refresh_token_repository.revoke_for_user_except_session(
                user_id,
                now,
                except_session_id=current_session_id,
            )
            await self.unit_of_work.commit()
            security_logger.info(
                "password_changed",
                extra={"event": "password_changed", "user_id": user_id},
            )

    @staticmethod
    def _is_expired(expires_at: datetime, now: datetime) -> bool:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return expires_at <= now

    @classmethod
    def _is_block_active(cls, block: BlockedDevice, now: datetime) -> bool:
        return block.is_permanent or block.blocked_until is None or not cls._is_expired(
            block.blocked_until,
            now,
        )

    @staticmethod
    def _authentication_response(
        user: User,
        raw_refresh_token: str,
        session_id: UUID | None = None,
    ) -> AuthenticationResponse:
        return AuthenticationResponse(
            access_token=create_access_token(
                str(user.id),
                session_id=str(session_id) if session_id is not None else None,
            ),
            refresh_token=raw_refresh_token,
            expires_in=settings.access_token_expire_minutes * 60,
            user=UserResponse.model_validate(user),
        )