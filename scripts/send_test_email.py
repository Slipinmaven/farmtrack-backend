import argparse
import asyncio
from pathlib import Path
import sys

import httpx
from pydantic import EmailStr, TypeAdapter, ValidationError

# Make direct execution from the backend root resolve the application package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.services.email_gateway_service import FarmTrackEmailService


async def send_test_email(recipient_email: str) -> None:
    async with httpx.AsyncClient(
        timeout=settings.email_gateway_timeout_seconds,
        follow_redirects=True,
    ) as client:
        await FarmTrackEmailService(client).send_test_email(recipient_email)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Send a real test email using the configured FarmTrack Email Gateway."
        )
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
