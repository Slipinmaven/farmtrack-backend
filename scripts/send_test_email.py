import argparse
import asyncio
from pathlib import Path
import sys

from pydantic import EmailStr, TypeAdapter, ValidationError

# Make direct execution from the backend root resolve the application package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.smtp_email_service import SMTPEmailService


async def send_test_email(recipient_email: str) -> None:
    await SMTPEmailService().send_test_email(recipient_email)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send a real test email using the configured Gmail SMTP account."
    )
    parser.add_argument(
        "recipient",
        help="Email address you control; a real email will be sent.",
    )
    args = parser.parse_args()

    try:
        recipient = str(TypeAdapter(EmailStr).validate_python(args.recipient))
    except ValidationError:
        parser.error("Enter a valid recipient email address.")

    try:
        asyncio.run(send_test_email(recipient))
    except RuntimeError as exc:
        parser.error(str(exc))

    print(f"Test email sent to {recipient}.")


if __name__ == "__main__":
    main()
