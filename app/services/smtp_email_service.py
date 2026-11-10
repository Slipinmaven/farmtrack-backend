import asyncio
from html import escape
import smtplib
import ssl
from email.message import EmailMessage
from datetime import datetime
from uuid import UUID

from app.core.config import settings
from app.models.farm_membership import FarmMembership
from app.schemas.enums import FarmRole


class SMTPEmailService:
    def __init__(self) -> None:
        self.host = settings.smtp_host
        self.port = settings.smtp_port
        self.username = settings.smtp_username
        self.password = settings.smtp_password
        self.from_email = settings.smtp_from_email or self.username

    @property
    def is_configured(self) -> bool:
        return (
            self.username is not None
            and self.password is not None
            and self.from_email is not None
        )

    async def send_farm_invitation(
        self,
        *,
        membership: FarmMembership,
        idempotency_key: UUID,
        farm_name: str | None = None,
        recipient_email: str | None = None,
    ) -> None:
        farm_name = farm_name or membership.farm.name
        recipient_email = recipient_email or membership.user.email
        role = FarmRole(membership.role).value
        app_url = settings.farmtrack_app_url
        message = EmailMessage()
        message["From"] = self._require_sender()
        message["To"] = recipient_email
        message["Subject"] = f"Invitation to join {farm_name} on FarmTrack"
        message["X-FarmTrack-Delivery-ID"] = str(idempotency_key)
        message.set_content(
            f"You have been invited to join {farm_name} on FarmTrack as a {role}.\n\n"
            "Open FarmTrack and sign in with the invited email address. Then open "
            "Account > Team & invitations to accept the invitation.\n\n"
            f"Open FarmTrack: {app_url}\n\n"
            "If the farm owner created your account, ask them to share your initial "
            "password with you through a secure channel. FarmTrack will never include "
            "that password in this email."
        )
        message.add_alternative(
            self._invitation_html(farm_name, role, app_url),
            subtype="html",
        )
        await self._send_message(message, "invitation")

    async def send_test_email(self, recipient_email: str) -> None:
        message = EmailMessage()
        message["From"] = self._require_sender()
        message["To"] = recipient_email
        message["Subject"] = "FarmTrack email configuration test"
        message.set_content(
            "This is a test email from FarmTrack. "
            "Your Gmail SMTP configuration is working."
        )
        await self._send_message(message, "test")

    async def send_release_download_invitation(
        self,
        *,
        recipient_email: str,
        version: str,
        release_notes: str | None,
        download_url: str,
        download_password: str,
        expires_at: datetime,
        delivery_id: UUID,
    ) -> None:
        expiry_text = expires_at.strftime("%B %d, %Y").replace(" 0", " ")
        message = EmailMessage()
        message["From"] = self._require_sender()
        message["To"] = recipient_email
        message["Subject"] = "Download FarmTrack for Android"
        message["X-FarmTrack-Delivery-ID"] = str(delivery_id)
        notes_text = f"\n\nRelease notes:\n{release_notes}" if release_notes else ""
        message.set_content(
            f"FarmTrack for Android, version {version}, is ready to download."
            f"{notes_text}\n\n"
            f"Download FarmTrack: {download_url}\n\n"
            f"Download password: {download_password}\n\n"
            f"This link expires on {expiry_text}. "
            "Open the link on your Android device, download the APK, and open "
            "the downloaded file to install it. If prompted, allow your browser "
            "or file manager to install apps from this source.\n\n"
            "Only install FarmTrack if you trust the person who sent you this email."
        )
        message.add_alternative(
            self._release_download_html(
                version=version,
                release_notes=release_notes,
                download_url=download_url,
                download_password=download_password,
                expiry_text=expiry_text,
            ),
            subtype="html",
        )
        await self._send_message(message, "release download")

    @staticmethod
    def _release_download_html(
        *,
        version: str,
        release_notes: str | None,
        download_url: str,
        download_password: str,
        expiry_text: str,
    ) -> str:
        safe_version = escape(version)
        safe_url = escape(download_url, quote=True)
        safe_password = escape(download_password)
        notes_html = ""
        if release_notes:
            notes_html = (
                '<div style="margin-top:24px;padding:18px;border-radius:10px;'
                'background:#f3f6f2;"><strong>What\'s new</strong>'
                f'<p style="margin:8px 0 0;white-space:pre-line;">'
                f'{escape(release_notes)}</p></div>'
            )
        safe_expiry = escape(expiry_text)
        return f"""\
<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Download FarmTrack</title></head>
  <body style="margin:0;padding:0;background:#f3f6f2;font-family:Arial,Helvetica,sans-serif;color:#243128;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="padding:32px 12px;background:#f3f6f2;">
      <tr><td align="center">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#fff;border:1px solid #e3e9e1;border-radius:16px;overflow:hidden;">
          <tr><td style="padding:24px 32px;background:#205c3b;color:#fff;">
            <div style="font-size:13px;font-weight:bold;letter-spacing:1.5px;text-transform:uppercase;">FarmTrack</div>
            <div style="margin-top:8px;font-size:14px;color:#dcebdd;">Farm work, together.</div>
          </td></tr>
          <tr><td style="padding:36px 32px 28px;">
            <div style="font-size:28px;line-height:1.2;font-weight:bold;">FarmTrack for Android</div>
            <p style="margin:12px 0 0;font-size:16px;line-height:1.6;color:#536157;">Version <strong>{safe_version}</strong> is ready. Download the app using the secure link below.</p>
            {notes_html}
            <table role="presentation" cellspacing="0" cellpadding="0" style="margin-top:28px;">
              <tr><td align="center" style="border-radius:8px;background:#28734a;">
                <a href="{safe_url}" style="display:inline-block;padding:15px 24px;color:#fff;text-decoration:none;font-size:16px;font-weight:bold;">Download FarmTrack</a>
              </td></tr>
            </table>
            <p style="margin:20px 0 0;font-size:13px;line-height:1.6;color:#536157;">Button not working? Copy this link into your browser:<br><a href="{safe_url}" style="color:#205c3b;word-break:break-all;">{safe_url}</a></p>
            <div style="margin-top:18px;padding:16px;border:1px solid #d5e5d8;border-radius:10px;background:#f4f8f4;">
              <strong style="font-size:14px;">Download password</strong>
              <p style="margin:8px 0 0;font-size:20px;font-weight:bold;letter-spacing:2px;color:#205c3b;">{safe_password}</p>
              <p style="margin:8px 0 0;font-size:12px;line-height:1.5;color:#536157;">Enter this password on the download page. Keep it private.</p>
            </div>
            <div style="margin-top:24px;padding:18px;border-radius:10px;background:#f3f6f2;">
              <strong style="font-size:14px;">Install on Android</strong>
              <ol style="margin:8px 0 0;padding-left:20px;font-size:13px;line-height:1.7;color:#536157;">
                <li>Open this email on your Android device and tap Download FarmTrack.</li>
                <li>Open the downloaded APK and follow the installation prompts.</li>
                <li>If asked, allow your browser or file manager to install apps from this source.</li>
              </ol>
            </div>
            <p style="margin:18px 0 0;font-size:12px;line-height:1.5;color:#78837a;">For your security, this download link expires on {safe_expiry}. Only install the app if you trust the person who sent this email.</p>
          </td></tr>
          <tr><td style="padding:18px 32px;border-top:1px solid #edf0ec;font-size:12px;color:#78837a;">FarmTrack · Poultry farm management</td></tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>"""

    @staticmethod
    def _invitation_html(farm_name: str, role: str, app_url: str) -> str:
        safe_farm_name = escape(farm_name)
        safe_role = escape(role)
        safe_app_url = escape(app_url, quote=True)
        return f"""\
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>You're invited to FarmTrack</title>
  </head>
  <body style="margin:0;padding:0;background-color:#f3f6f2;font-family:Arial,Helvetica,sans-serif;color:#243128;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:#f3f6f2;padding:32px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background-color:#ffffff;border:1px solid #e3e9e1;border-radius:16px;overflow:hidden;">
            <tr>
              <td style="padding:24px 32px;background-color:#205c3b;color:#ffffff;">
                <div style="font-size:13px;font-weight:bold;letter-spacing:1.5px;text-transform:uppercase;">FarmTrack</div>
                <div style="margin-top:8px;font-size:14px;color:#dcebdd;">Farm work, together.</div>
              </td>
            </tr>
            <tr>
              <td style="padding:36px 32px 24px;">
                <div style="font-size:30px;line-height:1.2;font-weight:bold;color:#243128;">You're invited!</div>
                <p style="margin:18px 0 0;font-size:16px;line-height:1.6;color:#536157;">
                  You have been invited to join <strong style="color:#243128;">{safe_farm_name}</strong> as a <strong style="color:#243128;">{safe_role}</strong>.
                </p>
                <p style="margin:14px 0 0;font-size:16px;line-height:1.6;color:#536157;">
                  Sign in to FarmTrack with this email address, then open <strong>Account &gt; Team &amp; invitations</strong> to accept.
                </p>
                <table role="presentation" cellspacing="0" cellpadding="0" style="margin-top:28px;">
                  <tr>
                    <td align="center" style="border-radius:8px;background-color:#28734a;">
                      <a href="{safe_app_url}" style="display:inline-block;padding:14px 22px;color:#ffffff;text-decoration:none;font-size:15px;font-weight:bold;">Open FarmTrack</a>
                    </td>
                  </tr>
                </table>
                <div style="margin-top:28px;padding:16px 18px;border-radius:10px;background-color:#f3f6f2;">
                  <p style="margin:0;font-size:13px;line-height:1.6;color:#536157;">
                    <strong style="color:#243128;">A quick security note</strong><br>
                    If the farm owner created your account, they will share your initial password separately. FarmTrack will never send your password by email.
                  </p>
                </div>
              </td>
            </tr>
            <tr>
              <td style="padding:18px 32px;border-top:1px solid #edf0ec;font-size:12px;line-height:1.5;color:#78837a;">
                This email was sent because a farm owner invited you to their FarmTrack team. If you weren't expecting it, you can ignore this message.
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""

    def _require_sender(self) -> str:
        if not self.is_configured:
            raise RuntimeError(
                "Gmail SMTP email delivery is not configured. "
                "Set SMTP_USERNAME and SMTP_PASSWORD."
            )
        if self.from_email is None:
            raise RuntimeError("SMTP_FROM_EMAIL could not be determined.")
        return self.from_email

    async def _send_message(self, message: EmailMessage, email_kind: str) -> None:
        self._require_sender()
        if self.username is None or self.password is None:
            raise RuntimeError("Gmail SMTP email delivery is not configured.")
        try:
            await asyncio.to_thread(self._send_message_sync, message)
        except (smtplib.SMTPException, OSError) as exc:
            raise RuntimeError(
                f"Gmail SMTP delivery failed for {email_kind} email "
                f"({type(exc).__name__})."
            ) from exc

    def _send_message_sync(self, message: EmailMessage) -> None:
        if self.username is None or self.password is None:
            raise RuntimeError("Gmail SMTP email delivery is not configured.")
        with smtplib.SMTP(self.host, self.port, timeout=15) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(self.username, self.password.get_secret_value())
            server.send_message(message)
