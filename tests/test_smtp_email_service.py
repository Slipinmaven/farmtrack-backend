import smtplib
from email.message import EmailMessage
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings, settings
from app.services.smtp_email_service import SMTPEmailService


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.credentials = None
        self.message = None
        self.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def starttls(self, *, context):
        self.started_tls = context is not None

    def login(self, username, password):
        self.credentials = (username, password)

    def send_message(self, message):
        self.message = message


@pytest.fixture(autouse=True)
def configured_smtp(monkeypatch):
    FakeSMTP.instances.clear()
    monkeypatch.setattr(settings, "smtp_host", "smtp.gmail.com")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_username", "farmtrack@gmail.com")
    monkeypatch.setattr(
        settings,
        "smtp_password",
        SecretStr("test-app-password"),
    )
    monkeypatch.setattr(settings, "smtp_from_email", None)
    monkeypatch.setattr(settings, "farmtrack_app_url", "farmtrack://farm-team")
    monkeypatch.setattr(
        "app.services.smtp_email_service.smtplib.SMTP",
        FakeSMTP,
    )


@pytest.mark.asyncio
async def test_gmail_smtp_sends_invitation_with_configured_account():
    membership = SimpleNamespace(
        farm=SimpleNamespace(name="Green Valley"),
        role="worker",
        user=SimpleNamespace(email="worker@example.com"),
    )
    delivery_id = uuid4()

    await SMTPEmailService().send_farm_invitation(
        membership=membership,
        idempotency_key=delivery_id,
    )

    smtp = FakeSMTP.instances[0]
    assert (smtp.host, smtp.port, smtp.timeout) == ("smtp.gmail.com", 587, 15)
    assert smtp.started_tls is True
    assert smtp.credentials == ("farmtrack@gmail.com", "test-app-password")
    assert isinstance(smtp.message, EmailMessage)
    assert smtp.message["From"] == "farmtrack@gmail.com"
    assert smtp.message["To"] == "worker@example.com"
    assert smtp.message["X-FarmTrack-Delivery-ID"] == str(delivery_id)
    assert "Green Valley" in smtp.message["Subject"]
    text_content = smtp.message.get_body(preferencelist=("plain",)).get_content()
    assert "farmtrack://farm-team" in text_content
    assert "long-initial-password" not in text_content
    html_content = smtp.message.get_body(preferencelist=("html",)).get_content()
    assert "You're invited!" in html_content
    assert "Green Valley" in html_content
    assert 'href="farmtrack://farm-team"' in html_content
    assert "FarmTrack will never send your password by email." in html_content


@pytest.mark.asyncio
async def test_invitation_html_escapes_farm_name_and_app_link(monkeypatch):
    membership = SimpleNamespace(
        farm=SimpleNamespace(name='<Farm "X">'),
        role="worker",
        user=SimpleNamespace(email="worker@example.com"),
    )
    from app.core.config import settings

    monkeypatch.setattr(
        settings,
        "farmtrack_app_url",
        'farmtrack://farm-team?name="x"&open=1',
    )
    await SMTPEmailService().send_farm_invitation(
        membership=membership,
        idempotency_key=uuid4(),
    )

    html_content = FakeSMTP.instances[0].message.get_body(
        preferencelist=("html",)
    ).get_content()
    assert "&lt;Farm &quot;X&quot;&gt;" in html_content
    assert 'href="farmtrack://farm-team?name=&quot;x&quot;&amp;open=1"' in html_content
    assert '<Farm "X">' not in html_content


@pytest.mark.asyncio
async def test_test_email_uses_configured_sender_and_requested_recipient():
    await SMTPEmailService().send_test_email("recipient@example.com")

    message = FakeSMTP.instances[0].message
    assert message["From"] == "farmtrack@gmail.com"
    assert message["To"] == "recipient@example.com"
    assert message["Subject"] == "FarmTrack email configuration test"
    assert "Gmail SMTP configuration is working" in message.get_content()


@pytest.mark.asyncio
async def test_release_download_email_has_html_and_text_alternatives():
    from datetime import datetime, timezone

    await SMTPEmailService().send_release_download_invitation(
        recipient_email="recipient@example.com",
        version="1.2.3",
        release_notes="<New fixes & improvements>",
        download_url="https://api.example.com/api/v1/downloads/secret-token",
        download_password="ABCD2345EFGH6789",
        expires_at=datetime(2026, 11, 16, tzinfo=timezone.utc),
        delivery_id=uuid4(),
    )

    message = FakeSMTP.instances[0].message
    text_content = message.get_body(preferencelist=("plain",)).get_content()
    html_content = message.get_body(preferencelist=("html",)).get_content()
    assert message["Subject"] == "Download FarmTrack for Android"
    assert "secret-token" in text_content
    assert "Download password: ABCD2345EFGH6789" in text_content
    assert "ABCD2345EFGH6789" in html_content
    assert "install apps from this source" in text_content
    assert "&lt;New fixes &amp; improvements&gt;" in html_content
    assert 'href="https://api.example.com/api/v1/downloads/secret-token"' in html_content
    assert "November 16, 2026" in html_content


@pytest.mark.asyncio
async def test_smtp_failure_does_not_expose_provider_response():
    class RejectingSMTP(FakeSMTP):
        def login(self, _username, _password):
            raise smtplib.SMTPAuthenticationError(
                535,
                b"sensitive provider response body",
            )

    with patch("app.services.smtp_email_service.smtplib.SMTP", RejectingSMTP):
        with pytest.raises(RuntimeError, match="SMTPAuthenticationError") as error:
            await SMTPEmailService().send_test_email("recipient@example.com")

    assert "sensitive provider response body" not in str(error.value)


def test_smtp_username_and_password_must_be_configured_together():
    with pytest.raises(ValidationError, match="SMTP_USERNAME and SMTP_PASSWORD"):
        Settings(
            _env_file=None,
            database_url="postgresql+asyncpg://user:pass@localhost/farmtrack",
            jwt_secret_key="a" * 32,
            smtp_username="farmtrack@gmail.com",
        )
