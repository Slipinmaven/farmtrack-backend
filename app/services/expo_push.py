import json
from urllib.request import Request, urlopen
from typing import Any


EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


def send_expo_push_notification(
    token: str,
    title: str,
    body: str,
    data: dict[str, Any] | None = None,
) -> None:
    request = Request(
        EXPO_PUSH_URL,
        data=json.dumps(
            {
                "to": token,
                "title": title,
                "body": body,
                "sound": "default",
                "data": data or {},
            }
        ).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        result = json.loads(response.read().decode("utf-8"))

    tickets = result.get("data", [])
    if isinstance(tickets, dict):
        tickets = [tickets]
    if not isinstance(tickets, list) or not tickets:
        raise RuntimeError("Expo push service returned no delivery ticket.")
    for ticket in tickets:
        if ticket.get("status") != "ok":
            raise RuntimeError("Expo push service rejected the notification.")