import asyncio
import unittest
from uuid import uuid4

from pydantic import SecretStr, ValidationError

from app.core.exceptions import DeviceBlockedError
from app.core.request_context import auth_session_id_context
from app.core.security import decode_access_token, hash_device_id, hash_password
from app.models.user import User
from app.schemas.auth import DeviceBlockRequest, LoginRequest
from app.schemas.enums import ActivityEntityType, ActivityType
from app.services.auth_service import AuthService
from app.services.activity_service import ActivityService


class AuthSessionSchemaTests(unittest.TestCase):
    def test_login_requires_and_normalizes_device_id(self):
        request = LoginRequest.model_validate(
            {
                "email": "person@example.com",
                "password": "long-enough-password",
                "device_id": "  device-installation-123  ",
            }
        )
        self.assertEqual(request.device_id, "device-installation-123")

        with self.assertRaises(ValidationError):
            LoginRequest.model_validate(
                {"email": "person@example.com", "password": "password"}
            )

        with self.assertRaises(ValidationError):
            LoginRequest.model_validate(
                {
                    "email": "person@example.com",
                    "password": "password",
                    "device_id": "                ",
                }
            )

    def test_device_block_requires_either_duration_or_permanent(self):
        temporary = DeviceBlockRequest.model_validate({"duration_days": 30})
        permanent = DeviceBlockRequest.model_validate({"permanent": True})
        self.assertEqual(temporary.duration_days, 30)
        self.assertTrue(permanent.permanent)

        for payload in ({}, {"permanent": True, "duration_days": 30}):
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    DeviceBlockRequest.model_validate(payload)

    def test_device_id_is_stored_as_a_stable_digest(self):
        device_id = "installation-id-123456"
        self.assertEqual(hash_device_id(device_id), hash_device_id(device_id))
        self.assertNotEqual(hash_device_id(device_id), device_id)
        self.assertEqual(len(hash_device_id(device_id)), 64)


class ActivitySessionAttributionTests(unittest.TestCase):
    def test_activity_records_authenticated_session_id(self):
        session_id = uuid4()

        class Repository:
            async def create(self, activity):
                return activity

        service = ActivityService(repository=Repository(), unit_of_work=None)

        async def record():
            return await service.record(
                farm_id=uuid4(),
                user_id=uuid4(),
                activity_type=ActivityType.FARM_UPDATED,
                entity_type=ActivityEntityType.FARM,
                entity_id=uuid4(),
            )

        context_token = auth_session_id_context.set(session_id)
        try:
            activity = asyncio.run(record())
        finally:
            auth_session_id_context.reset(context_token)

        self.assertEqual(activity.session_id, session_id)

    def test_background_activity_has_no_session(self):
        class Repository:
            async def create(self, activity):
                return activity

        service = ActivityService(repository=Repository(), unit_of_work=None)

        async def record():
            return await service.record(
                farm_id=uuid4(),
                user_id=None,
                activity_type=ActivityType.FARM_UPDATED,
                entity_type=ActivityEntityType.FARM,
                entity_id=uuid4(),
            )

        activity = asyncio.run(record())
        self.assertIsNone(activity.session_id)


class LoginSessionBindingTests(unittest.TestCase):
    def test_login_binds_refresh_and_access_tokens_to_created_session(self):
        user = User(
            id=uuid4(),
            email="person@example.com",
            password_hash=hash_password("correct horse battery staple"),
            is_active=True,
        )

        class UserRepo:
            async def get_by_email(self, _email):
                return user

        class RefreshRepo:
            token = None

            async def create(self, token):
                token.id = uuid4()
                self.token = token
                return token

        class SessionRepo:
            user_session = None

            async def get_device_block(self, _user_id, _device_key):
                return None

            async def create(self, user_session):
                user_session.id = uuid4()
                self.user_session = user_session
                return user_session

        class UnitOfWork:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def commit(self):
                return None

        refresh_repo = RefreshRepo()
        session_repo = SessionRepo()
        auth_service = AuthService(
            user_repository=UserRepo(),
            refresh_token_repository=refresh_repo,
            user_session_repository=session_repo,
            unit_of_work=UnitOfWork(),
        )

        response = asyncio.run(
            auth_service.login_user(
                email=user.email,
                password=SecretStr("correct horse battery staple"),
                device_id="installation-id-123456",
                device_name="Test phone",
                platform="Android 15",
                ip_address="192.0.2.1",
                user_agent="FarmTrack test client",
            )
        )

        access_payload = decode_access_token(response.access_token)
        self.assertEqual(access_payload["sid"], str(session_repo.user_session.id))
        self.assertEqual(refresh_repo.token.session_id, session_repo.user_session.id)
        self.assertEqual(
            session_repo.user_session.device_key,
            hash_device_id("installation-id-123456"),
        )
        self.assertEqual(session_repo.user_session.ip_address, "192.0.2.1")
        self.assertIsNotNone(user.last_login_at)

    def test_blocked_device_raises_dedicated_error_code(self):
        user = User(
            id=uuid4(),
            email="person@example.com",
            password_hash=hash_password("correct horse battery staple"),
            is_active=True,
        )

        class UserRepo:
            async def get_by_email(self, _email):
                return user

        class RefreshRepo:
            async def create(self, _token):
                raise AssertionError("Blocked devices must not receive refresh tokens.")

        class SessionRepo:
            async def get_device_block(self, _user_id, _device_key):
                return type("Block", (), {"is_permanent": True, "blocked_until": None})()

            async def create(self, _user_session):
                raise AssertionError("Blocked devices must not create sessions.")

        class UnitOfWork:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

        auth_service = AuthService(
            user_repository=UserRepo(),
            refresh_token_repository=RefreshRepo(),
            user_session_repository=SessionRepo(),
            unit_of_work=UnitOfWork(),
        )

        with self.assertRaises(DeviceBlockedError) as error:
            asyncio.run(
                auth_service.login_user(
                    email=user.email,
                    password=SecretStr("correct horse battery staple"),
                    device_id="installation-id-blocked",
                )
            )

        self.assertEqual(error.exception.code, "DEVICE_BLOCKED")
        self.assertEqual(error.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()