from email.message import EmailMessage
from datetime import datetime
from html import escape
from uuid import UUID

import httpx

from app.core.config import settings
from app.models.farm_membership import FarmMembership
from app.schemas.enums import FarmRole


class FarmTrackEmailService:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.client = client

    @property
    def is_configured(self) -> bool:
        return (
            settings.email_gateway_url is not None
            and settings.email_gateway_secret is not None
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
        message["To"] = recipient_email
        message["Subject"] = f"Invitation to join {farm_name} on FarmTrack"
        message["X-FarmTrack-Delivery-ID"] = str(idempotency_key)
        message.set_content(
            f"You have been invited to join {farm_name} on FarmTrack as a {role}.\n\n"
            "To join, open FarmTrack and sign in with the email address this "
            "message was sent to. Open More > Team & invitations and accept "
            "the invitation. If you do not have a FarmTrack account yet, ask "
            "the farm owner for sign-in instructions.\n\n"
            f"Open FarmTrack: {app_url}\n\n"
            "Your farm role is shown in this invitation. Managers can manage "
            "farm team access; workers can use the farm workspace with worker "
            "permissions.\n\n"
            "If you were not expecting this invitation or do not recognize the "
            "farm, ignore this email. FarmTrack will never include your password "
            "in an invitation email."
        )
        message.add_alternative(
            self._invitation_html(farm_name, role, app_url),
            subtype="html",
        )
        await self._send_message(message, "invitation")

    async def send_farm_member_left_notice(
        self,
        *,
        recipient_email: str,
        farm_name: str,
        member_email: str,
    ) -> None:
        message = EmailMessage()
        message["To"] = recipient_email
        message["Subject"] = f"A member left {farm_name}"
        message.set_content(
            "Hello,\n\n"
            f"{member_email} has left {farm_name}. Their access to the farm "
            "workspace has ended. The farm and its records have not been "
            "deleted and remain under your ownership.\n\n"
            "You can review the current team from FarmTrack's team settings.\n\n"
            "FarmTrack\n"
            "This is an automated farm access notice."
        )
        message.add_alternative(
            self._farm_member_left_html(
                farm_name=farm_name,
                member_email=member_email,
            ),
            subtype="html",
        )
        await self._send_message(message, "farm member left notice")

    async def send_farm_left_confirmation(
        self,
        *,
        recipient_email: str,
        farm_name: str,
        owner_notified: bool,
    ) -> None:
        notification_copy = (
            "The farm owner has been notified."
            if owner_notified
            else "We could not email the farm owner. Please contact them directly."
        )
        message = EmailMessage()
        message["To"] = recipient_email
        message["Subject"] = f"You have left {farm_name}"
        message.set_content(
            "Hello,\n\n"
            f"You have left {farm_name}. Your access to its workspace ended "
            "immediately. The farm and its records remain with the farm owner; "
            "nothing was deleted.\n\n"
            f"{notification_copy} If you need access again, ask "
            "them to invite you back to the farm.\n\n"
            "FarmTrack\n"
            "This is an automated farm access confirmation."
        )
        message.add_alternative(
            self._farm_left_confirmation_html(
                farm_name=farm_name,
                owner_notified=owner_notified,
            ),
            subtype="html",
        )
        await self._send_message(message, "farm leave confirmation")

    async def send_test_email(self, recipient_email: str) -> None:
        message = EmailMessage()
        message["To"] = recipient_email
        message["Subject"] = "FarmTrack email configuration test"
        message.set_content(
            "This is a test email from FarmTrack. "
            "The FarmTrack Email Gateway is working."
        )
        await self._send_message(message, "test")

    @staticmethod
    def _farm_member_left_html(*, farm_name: str, member_email: str) -> str:
        safe_farm_name = escape(farm_name)
        safe_member_email = escape(member_email)
        return f"""\
<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
  <body style="margin:0;padding:24px 12px;background:#F1F4F1;font-family:Arial,Helvetica,sans-serif;color:#26352C;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;margin:0 auto;background:#FFFFFF;border:1px solid #D9E2DC;border-radius:16px;overflow:hidden;">
      <tr><td style="padding:22px 24px;background:#17473B;color:#FFFFFF;">
        <div style="font-size:12px;letter-spacing:1px;text-transform:uppercase;color:#D7E9E0;">FarmTrack · team update</div>
        <div style="margin-top:8px;font-size:24px;line-height:1.3;font-weight:bold;">A team member has left</div>
      </td></tr>
      <tr><td style="padding:24px;">
        <p style="margin:0;font-size:16px;line-height:1.6;">Hello,</p>
        <p style="margin:12px 0 0;font-size:16px;line-height:1.6;"><strong>{safe_member_email}</strong> has left <strong>{safe_farm_name}</strong>. Their access to the farm workspace has ended.</p>
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:20px;background:#F0F6F1;border:1px solid #D2E2D6;border-left:4px solid #287353;border-radius:10px;">
          <tr><td style="padding:14px;font-size:14px;line-height:1.6;">Your farm and its records are unchanged and remain under your ownership. Review the current team in FarmTrack's team settings.</td></tr>
        </table>
        <p style="margin:20px 0 0;font-size:13px;line-height:1.5;color:#627067;">This is an automated farm access notice from FarmTrack.</p>
      </td></tr>
    </table>
  </body>
</html>"""

    @staticmethod
    def _farm_left_confirmation_html(
        *,
        farm_name: str,
        owner_notified: bool,
    ) -> str:
        safe_farm_name = escape(farm_name)
        notification_copy = (
            "The farm owner has been notified. If you need access again, ask "
            "them to invite you back."
            if owner_notified
            else "We could not email the farm owner. Please contact them directly "
            "if they need to know. Ask them to invite you again if you need access."
        )
        return f"""\
<!doctype html>
<html lang="en">
  <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
  <body style="margin:0;padding:24px 12px;background:#F1F4F1;font-family:Arial,Helvetica,sans-serif;color:#26352C;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;margin:0 auto;background:#FFFFFF;border:1px solid #D9E2DC;border-radius:16px;overflow:hidden;">
      <tr><td style="padding:22px 24px;background:#17473B;color:#FFFFFF;">
        <div style="font-size:12px;letter-spacing:1px;text-transform:uppercase;color:#D7E9E0;">FarmTrack · access update</div>
        <div style="margin-top:8px;font-size:24px;line-height:1.3;font-weight:bold;">You have left the farm</div>
      </td></tr>
      <tr><td style="padding:24px;">
        <p style="margin:0;font-size:16px;line-height:1.6;">Hello,</p>
        <p style="margin:12px 0 0;font-size:16px;line-height:1.6;">Your access to <strong>{safe_farm_name}</strong> has ended. The farm and its records remain with the farm owner; nothing was deleted.</p>
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:20px;background:#F0F6F1;border:1px solid #D2E2D6;border-left:4px solid #287353;border-radius:10px;">
          <tr><td style="padding:14px;font-size:14px;line-height:1.6;">{escape(notification_copy)}</td></tr>
        </table>
        <p style="margin:20px 0 0;font-size:13px;line-height:1.5;color:#627067;">This is an automated farm access confirmation from FarmTrack.</p>
      </td></tr>
    </table>
  </body>
</html>"""

    async def send_account_deletion_notice(
        self,
        *,
        recipient_email: str,
        scheduled_for: datetime,
    ) -> None:
        deletion_date = scheduled_for.strftime("%B %d, %Y")
        message = EmailMessage()
        message["To"] = recipient_email
        message["Subject"] = "Your FarmTrack account deletion is scheduled"
        message.set_content(
            "Hello,\n\n"
            "You asked us to schedule deletion of your FarmTrack account. Your "
            "account and owned farms are set to be permanently deleted on "
            f"{deletion_date} (UTC).\n\n"
            "If you want the deletion to go ahead, you do not need to do anything. "
            "You will be signed out, sign-in will be blocked, and access to your "
            "owned farms will be paused during the 30-day recovery period. "
            "Changed your mind? Choose Restore scheduled account deletion on the "
            "sign-in screen and restore with your email and password. You will "
            "need to sign in again after restoration.\n\n"
            "If you did not request this, restore the account, change your "
            "password, and check your signed-in devices. If you cannot restore "
            "it, secure your email account and contact FarmTrack support.\n\n"
            "Take care,\nFarmTrack"
        )
        message.add_alternative(
            self._account_deletion_notice_html(
                deletion_date=deletion_date,
            ),
            subtype="html",
        )
        await self._send_message(message, "account deletion notice")

    async def send_account_restored_notice(
        self,
        *,
        recipient_email: str,
    ) -> None:
        message = EmailMessage()
        message["To"] = recipient_email
        message["Subject"] = "Your FarmTrack account is restored"
        message.set_content(
            "Hello,\n\n"
            "Your FarmTrack account deletion request has been cancelled. Your "
            "account access is active again, and farms and team memberships "
            "paused by that request have been restored.\n\n"
            "If you cancelled the request, there is nothing else you need to do. "
            "You can sign in to FarmTrack and continue using your workspace.\n\n"
            "If you did not cancel this request, change your password in "
            "FarmTrack and review Password & sign-in activity in Account & access. "
            "End any sessions you do not recognize.\n\n"
            "Take care,\nFarmTrack\n\n"
            "This is a security notice. Replies to this email are not monitored."
        )
        message.add_alternative(
            self._account_restored_html(),
            subtype="html",
        )
        await self._send_message(message, "account restored")

    @staticmethod
    def _account_restored_html() -> str:
        return """\
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="color-scheme" content="light">
    <title>Your FarmTrack account is restored</title>
  </head>
  <body bgcolor="#F1F4F1" style="margin:0;padding:0;background-color:#F1F4F1;font-family:Arial,Helvetica,sans-serif;color:#202923;-webkit-text-size-adjust:100%;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#F1F4F1" style="width:100%;background-color:#F1F4F1;">
      <tr><td align="center" style="padding:24px 12px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#FFFFFF" style="width:100%;max-width:560px;background-color:#FFFFFF;border:1px solid #D9E2DC;border-radius:16px;overflow:hidden;">
          <tr><td bgcolor="#17473B" style="padding:20px 24px;background-color:#17473B;color:#FFFFFF;">
            <div style="font-size:12px;line-height:1.5;font-weight:bold;letter-spacing:1.1px;text-transform:uppercase;color:#D7E9E0;">FarmTrack · account security</div>
            <div style="margin-top:9px;font-size:25px;line-height:1.25;font-weight:bold;color:#FFFFFF;">Your account is restored</div>
          </td></tr>
          <tr><td bgcolor="#FFFFFF" style="padding:24px;background-color:#FFFFFF;color:#26352C;">
            <p style="margin:0;font-size:16px;line-height:1.6;color:#39463D;">Hello,</p>
            <p style="margin:12px 0 0;font-size:16px;line-height:1.6;color:#39463D;">The deletion request for your FarmTrack account has been cancelled. Your account access is active again.</p>

            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#EAF5EE" style="margin-top:20px;width:100%;background-color:#EAF5EE;border:1px solid #B9D9C4;border-left:5px solid #287353;border-radius:10px;">
              <tr><td bgcolor="#EAF5EE" style="padding:16px;background-color:#EAF5EE;color:#244A35;">
                <table role="presentation" cellspacing="0" cellpadding="0" border="0">
                  <tr>
                    <td width="30" height="30" align="center" valign="middle" bgcolor="#D3EBDD" style="width:30px;height:30px;background-color:#D3EBDD;border-radius:15px;color:#287353;font-size:18px;font-weight:bold;">&#10003;</td>
                    <td style="padding-left:10px;font-size:15px;line-height:1.45;font-weight:bold;color:#244A35;">Your workspace is available again</td>
                  </tr>
                </table>
                <div style="margin-top:9px;font-size:14px;line-height:1.6;color:#3F5B49;">Farms and team memberships paused by the deletion request have been restored too. Sign in to FarmTrack to continue where you left off.</div>
              </td></tr>
            </table>

            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#FFF5E9" style="margin-top:18px;width:100%;background-color:#FFF5E9;border:1px solid #E8D2B5;border-left:5px solid #A35C2D;border-radius:10px;">
              <tr><td bgcolor="#FFF5E9" style="padding:15px 16px;background-color:#FFF5E9;color:#513A2A;">
                <div style="font-size:14px;line-height:1.45;font-weight:bold;color:#70431F;">Wasn’t this you?</div>
                <div style="margin-top:5px;font-size:14px;line-height:1.6;color:#5D4A3A;">Change your FarmTrack password, then open Account &amp; access &gt; Password &amp; sign-in activity and end any sessions you don’t recognize.</div>
              </td></tr>
            </table>

            <p style="margin:22px 0 0;font-size:15px;line-height:1.55;color:#39463D;">Take care,<br><strong style="color:#202923;">FarmTrack</strong></p>
          </td></tr>
          <tr><td bgcolor="#F3F5F3" style="padding:14px 24px;background-color:#F3F5F3;border-top:1px solid #E1E6E1;color:#657067;font-size:12px;line-height:1.6;">This is a security notice about your FarmTrack account. Replies to this email are not monitored.</td></tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>"""

    async def send_farm_deletion_notice(
        self,
        *,
        recipient_email: str,
        farm_name: str,
        scheduled_for: datetime,
    ) -> None:
        deletion_date = scheduled_for.strftime("%B %d, %Y")
        message = EmailMessage()
        message["To"] = recipient_email
        message["Subject"] = "A FarmTrack farm deletion is scheduled"
        message.set_content(
            f"Hello,\n\nYou asked us to schedule deletion of the FarmTrack farm "
            f"“{farm_name}”. Its records are set to be permanently deleted on "
            f"{deletion_date} (UTC).\n\n"
            "If you want the deletion to go ahead, you do not need to do anything. "
            "You have a 30-day recovery period to change your mind. Restore the "
            "farm in FarmTrack under Account & access > Farm recovery. Your "
            "password will be required.\n\n"
            "If you did not ask for this, restore the farm before the deadline, "
            "then change your password and review your signed-in devices. If you "
            "cannot sign in, contact FarmTrack support through your usual channel.\n\n"
            "Take care,\n"
            "FarmTrack"
        )
        message.add_alternative(
            self._farm_deletion_notice_html(
                farm_name=farm_name,
                deletion_date=deletion_date,
            ),
            subtype="html",
        )
        await self._send_message(message, "farm deletion notice")

    @staticmethod
    def _farm_deletion_notice_html(*, farm_name: str, deletion_date: str) -> str:
        safe_farm_name = escape(farm_name)
        safe_deletion_date = escape(deletion_date)
        return f"""\
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Farm deletion scheduled</title>
  </head>
  <body bgcolor="#F1F3F0" style="margin:0;padding:0;background-color:#F1F3F0;font-family:Arial,Helvetica,sans-serif;color:#202923;-webkit-text-size-adjust:100%;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" bgcolor="#F1F3F0" style="width:100%;background-color:#F1F3F0;">
      <tr><td align="center" style="padding:28px 12px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" bgcolor="#FFFFFF" style="width:100%;max-width:560px;background-color:#FFFFFF;border:1px solid #D8DED8;border-radius:16px;overflow:hidden;">
          <tr><td bgcolor="#913922" style="padding:20px 24px;background-color:#913922;color:#FFFFFF;">
            <table role="presentation" cellspacing="0" cellpadding="0">
              <tr>
                <td width="38" height="38" align="center" valign="middle" bgcolor="#B94E31" style="width:38px;height:38px;background-color:#B94E31;border-radius:19px;color:#FFFFFF;font-size:22px;font-weight:bold;">!</td>
                <td style="padding-left:12px;color:#FFFFFF;font-size:12px;line-height:1.4;font-weight:bold;letter-spacing:1.2px;text-transform:uppercase;">FarmTrack · important account notice</td>
              </tr>
            </table>
            <div style="margin-top:14px;color:#FFFFFF;font-size:24px;line-height:1.25;font-weight:bold;">Farm deletion scheduled</div>
          </td></tr>
          <tr><td bgcolor="#FFFFFF" style="padding:26px 24px 24px;background-color:#FFFFFF;color:#202923;">
            <p style="margin:0;font-size:16px;line-height:1.6;color:#39463D;">Hello,</p>
            <p style="margin:12px 0 0;font-size:16px;line-height:1.6;color:#39463D;">You asked us to schedule deletion of <strong style="color:#202923;">{safe_farm_name}</strong>. Its records are set to be permanently deleted on:</p>

            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" bgcolor="#FFF0D7" style="margin-top:20px;width:100%;background-color:#FFF0D7;border:1px solid #E8BD78;border-left:5px solid #B94E31;border-radius:10px;">
              <tr><td bgcolor="#FFF0D7" style="padding:15px 16px;background-color:#FFF0D7;color:#53351A;">
                <div style="font-size:11px;line-height:1.4;font-weight:bold;letter-spacing:1px;text-transform:uppercase;color:#74451F;">Permanent deletion date · UTC</div>
                <div style="margin-top:5px;font-size:21px;line-height:1.35;font-weight:bold;color:#35251A;">{safe_deletion_date}</div>
              </td></tr>
            </table>

            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" bgcolor="#F3F6F2" style="margin-top:16px;width:100%;background-color:#F3F6F2;border:1px solid #DCE4DA;border-radius:10px;">
              <tr><td bgcolor="#F3F6F2" style="padding:15px 16px;background-color:#F3F6F2;color:#28352C;">
                <div style="font-size:15px;line-height:1.45;font-weight:bold;color:#28352C;">You have a 30-day recovery period to change your mind</div>
                <div style="margin-top:5px;font-size:14px;line-height:1.6;color:#4D5C50;">If you want the deletion to go ahead, you do not need to do anything. Changed your mind? Open FarmTrack and go to Account &amp; access &gt; Farm recovery to restore the farm. You will need your password.</div>
              </td></tr>
            </table>

            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" bgcolor="#FCE9E3" style="margin-top:16px;width:100%;background-color:#FCE9E3;border:1px solid #E8B4A3;border-left:5px solid #913922;border-radius:10px;">
              <tr><td bgcolor="#FCE9E3" style="padding:15px 16px;background-color:#FCE9E3;color:#4D241B;">
                <div style="font-size:14px;line-height:1.45;font-weight:bold;color:#762E20;">If you did not request this</div>
                <div style="margin-top:5px;font-size:14px;line-height:1.6;color:#4D332E;">Please restore the farm before the date above. Then change your password and check your signed-in devices. If you cannot sign in, contact FarmTrack support.</div>
              </td></tr>
            </table>

            <p style="margin:22px 0 0;font-size:15px;line-height:1.55;color:#39463D;">Take care,<br><strong style="color:#202923;">FarmTrack</strong></p>
          </td></tr>
          <tr><td bgcolor="#F3F4F2" style="padding:13px 24px;background-color:#F3F4F2;border-top:1px solid #E1E5E0;color:#657067;font-size:12px;line-height:1.5;">This is a security notice about your FarmTrack account. Replies to this email are not monitored.</td></tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>"""

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
    <meta name="color-scheme" content="light">
    <title>You're invited to FarmTrack</title>
  </head>
  <body bgcolor="#F1F4F1" style="margin:0;padding:0;background-color:#F1F4F1;font-family:Arial,Helvetica,sans-serif;color:#202923;-webkit-text-size-adjust:100%;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#F1F4F1" style="width:100%;background-color:#F1F4F1;">
      <tr>
        <td align="center" style="padding:24px 12px;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#FFFFFF" style="width:100%;max-width:560px;background-color:#FFFFFF;border:1px solid #D9E2DC;border-radius:16px;overflow:hidden;">
            <tr>
              <td bgcolor="#17473B" style="padding:20px 24px;background-color:#17473B;color:#FFFFFF;">
                <div style="font-size:12px;line-height:1.5;font-weight:bold;letter-spacing:1.1px;text-transform:uppercase;color:#D7E9E0;">FarmTrack · farm team</div>
                <div style="margin-top:9px;font-size:25px;line-height:1.25;font-weight:bold;color:#FFFFFF;">You're invited!</div>
              </td>
            </tr>
            <tr>
              <td bgcolor="#FFFFFF" style="padding:24px;background-color:#FFFFFF;color:#26352C;">
                <p style="margin:0;font-size:16px;line-height:1.6;color:#39463D;">
                  You have been invited to join the FarmTrack farm:
                </p>
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#EEF5F0" style="margin-top:16px;width:100%;background-color:#EEF5F0;border:1px solid #D0E2D5;border-left:5px solid #287353;border-radius:10px;">
                  <tr><td bgcolor="#EEF5F0" style="padding:15px 16px;background-color:#EEF5F0;color:#244A35;">
                    <div style="font-size:11px;line-height:1.4;font-weight:bold;letter-spacing:1px;text-transform:uppercase;color:#526C59;">Farm</div>
                    <div style="margin-top:4px;font-size:19px;line-height:1.35;font-weight:bold;color:#202923;word-break:break-word;">{safe_farm_name}</div>
                    <div style="margin-top:10px;font-size:11px;line-height:1.4;font-weight:bold;letter-spacing:1px;text-transform:uppercase;color:#526C59;">Your role</div>
                    <div style="margin-top:4px;font-size:15px;line-height:1.45;font-weight:bold;color:#244A35;">{safe_role}</div>
                  </td></tr>
                </table>
                <p style="margin:18px 0 0;font-size:15px;line-height:1.6;color:#39463D;">
                  Accept using the FarmTrack account registered to the email address that received this invitation.
                </p>
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="margin-top:20px;">
                  <tr>
                    <td align="center" bgcolor="#287353" style="border-radius:10px;background-color:#287353;">
                      <a href="{safe_app_url}" style="display:block;padding:15px 18px;color:#FFFFFF;text-decoration:none;font-size:16px;line-height:1.35;font-weight:bold;">Open FarmTrack</a>
                    </td>
                  </tr>
                </table>
                <p style="margin:12px 0 0;font-size:13px;line-height:1.6;color:#647168;word-break:break-word;">
                  If the button does not open the app, open FarmTrack directly and go to <strong>More &gt; Team &amp; invitations</strong>.
                </p>
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#FFF5E9" style="margin-top:20px;width:100%;background-color:#FFF5E9;border:1px solid #E8D2B5;border-left:5px solid #A35C2D;border-radius:10px;">
                  <tr><td bgcolor="#FFF5E9" style="padding:14px 15px;background-color:#FFF5E9;color:#513A2A;">
                    <div style="font-size:14px;line-height:1.45;font-weight:bold;color:#70431F;">A note about account access</div>
                    <div style="margin-top:5px;font-size:13px;line-height:1.6;color:#5D4A3A;">If the farm owner created your account, ask them to share your initial password privately. FarmTrack will never send your password by email. If you do not recognize this farm or were not expecting an invitation, ignore this message.</div>
                  </td></tr>
                </table>
              </td>
            </tr>
            <tr>
              <td bgcolor="#F3F5F3" style="padding:14px 24px;background-color:#F3F5F3;border-top:1px solid #E1E6E1;font-size:12px;line-height:1.6;color:#657067;">
                This email was sent because a farm manager invited you to their FarmTrack team. Replies to this email are not monitored.
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""

    @staticmethod
    def _account_deletion_notice_html(
        *,
        deletion_date: str,
    ) -> str:
        safe_date = escape(deletion_date)
        return f"""\
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Account deletion scheduled</title>
  </head>
  <body bgcolor="#F1F3F0" style="margin:0;padding:0;background-color:#F1F3F0;font-family:Arial,Helvetica,sans-serif;color:#202923;-webkit-text-size-adjust:100%;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" bgcolor="#F1F3F0" style="width:100%;background-color:#F1F3F0;">
      <tr><td align="center" style="padding:28px 12px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" bgcolor="#FFFFFF" style="width:100%;max-width:560px;background-color:#FFFFFF;border:1px solid #D8DED8;border-radius:16px;overflow:hidden;">
          <tr><td bgcolor="#913922" style="padding:20px 24px;background-color:#913922;color:#FFFFFF;">
            <table role="presentation" cellspacing="0" cellpadding="0">
              <tr>
                <td width="38" height="38" align="center" valign="middle" bgcolor="#B94E31" style="width:38px;height:38px;background-color:#B94E31;border-radius:19px;color:#FFFFFF;font-size:22px;font-weight:bold;">!</td>
                <td style="padding-left:12px;color:#FFFFFF;font-size:12px;line-height:1.4;font-weight:bold;letter-spacing:1.2px;text-transform:uppercase;">FarmTrack · important account notice</td>
              </tr>
            </table>
            <div style="margin-top:14px;color:#FFFFFF;font-size:24px;line-height:1.25;font-weight:bold;">Account deletion scheduled</div>
          </td></tr>
          <tr><td bgcolor="#FFFFFF" style="padding:26px 24px 24px;background-color:#FFFFFF;color:#202923;">
            <p style="margin:0;font-size:16px;line-height:1.6;color:#39463D;">Hello,</p>
            <p style="margin:12px 0 0;font-size:16px;line-height:1.6;color:#39463D;">You asked us to schedule deletion of your FarmTrack account and owned farms. They are set to be permanently deleted on:</p>

            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" bgcolor="#FFF0D7" style="margin-top:20px;width:100%;background-color:#FFF0D7;border:1px solid #E8BD78;border-left:5px solid #B94E31;border-radius:10px;">
              <tr><td bgcolor="#FFF0D7" style="padding:15px 16px;background-color:#FFF0D7;color:#53351A;">
                <div style="font-size:11px;line-height:1.4;font-weight:bold;letter-spacing:1px;text-transform:uppercase;color:#74451F;">Permanent deletion date · UTC</div>
                <div style="margin-top:5px;font-size:21px;line-height:1.35;font-weight:bold;color:#35251A;">{safe_date}</div>
              </td></tr>
            </table>

            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" bgcolor="#F3F6F2" style="margin-top:16px;width:100%;background-color:#F3F6F2;border:1px solid #DCE4DA;border-radius:10px;">
              <tr><td bgcolor="#F3F6F2" style="padding:15px 16px;background-color:#F3F6F2;color:#28352C;">
                <div style="font-size:15px;line-height:1.45;font-weight:bold;color:#28352C;">You have 30 days to change your mind</div>
                <div style="margin-top:5px;font-size:14px;line-height:1.6;color:#4D5C50;">You will be signed out, sign-in will be blocked, and access to your owned farms will be paused during the recovery period. Changed your mind? Choose Restore scheduled account deletion on the sign-in screen and restore with your email and password. You will need to sign in again afterward.</div>
              </td></tr>
            </table>

            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" bgcolor="#FCE9E3" style="margin-top:16px;width:100%;background-color:#FCE9E3;border:1px solid #E8B4A3;border-left:5px solid #913922;border-radius:10px;">
              <tr><td bgcolor="#FCE9E3" style="padding:15px 16px;background-color:#FCE9E3;color:#4D241B;">
                <div style="font-size:14px;line-height:1.45;font-weight:bold;color:#762E20;">If you did not request this</div>
                <div style="margin-top:5px;font-size:14px;line-height:1.6;color:#4D332E;">Restore the account from the sign-in screen, then change your password and review signed-in devices. If you cannot restore it, secure your email account and contact FarmTrack support.</div>
              </td></tr>
            </table>

            <p style="margin:22px 0 0;font-size:15px;line-height:1.55;color:#39463D;">Take care,<br><strong style="color:#202923;">FarmTrack</strong></p>
          </td></tr>
          <tr><td bgcolor="#F3F4F2" style="padding:13px 24px;background-color:#F3F4F2;border-top:1px solid #E1E5E0;color:#657067;font-size:12px;line-height:1.5;">This is a security notice about your FarmTrack account. Replies to this email are not monitored.</td></tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>"""

    async def _send_message(self, message: EmailMessage, email_kind: str) -> None:
        gateway_url = settings.email_gateway_url
        gateway_secret = settings.email_gateway_secret
        if gateway_url is None or gateway_secret is None:
            raise RuntimeError("FarmTrack email gateway is not configured.")
        if self.client is None:
            raise RuntimeError("FarmTrack email gateway client is unavailable.")

        plain_body = message.get_body(preferencelist=("plain",))
        if plain_body is None:
            raise RuntimeError("Email message has no plain-text body.")
        html_body = message.get_body(preferencelist=("html",))
        payload = {
            "apiKey": gateway_secret.get_secret_value(),
            "to": str(message["To"]),
            "subject": str(message["Subject"]),
            "textBody": plain_body.get_content(),
        }
        if html_body is not None:
            payload["htmlBody"] = html_body.get_content()

        try:
            response = await self.client.post(
                gateway_url,
                json=payload,
            )
            response.raise_for_status()
        except httpx.TimeoutException:
            raise RuntimeError(
                f"FarmTrack email gateway timed out for {email_kind} email."
            ) from None
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"FarmTrack email gateway returned an unsuccessful HTTP status "
                f"({exc.response.status_code}) for {email_kind} email."
            ) from None
        except httpx.RequestError:
            raise RuntimeError(
                f"FarmTrack email gateway request failed for {email_kind} email."
            ) from None

        try:
            result = response.json()
        except (ValueError, TypeError):
            raise RuntimeError(
                f"FarmTrack email gateway returned an invalid response for "
                f"{email_kind} email."
            ) from None

        if not isinstance(result, dict) or type(result.get("ok")) is not bool:
            raise RuntimeError(
                f"FarmTrack email gateway returned an invalid response for "
                f"{email_kind} email."
            )
        if not result["ok"]:
            raise RuntimeError(
                f"FarmTrack email gateway rejected the {email_kind} email."
            )
