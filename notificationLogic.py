import jwt
import time
import httpx

from config import (
    APNS_TEAM_ID,
    APNS_KEY,
    APNS_KEY_ID,
    APNS_BUNDLE_ID
)

APNS_HOST = "api.sandbox.push.apple.com"


def get_apns_token():
    payload = {
        "iss": APNS_TEAM_ID,
        "iat": time.time()
    }

    return jwt.encode(
        payload,
        APNS_KEY,
        algorithm="ES256",
        headers={"kid": APNS_KEY_ID}
    )


def send_push_notification(
    device_token: str,
    title: str,
    body: str,
    sender_name: str,
    sender_id: str,
    conversation_id: str,
    image_url: str = None,
    data: dict = {}
):
    token = get_apns_token()
    url = f"https://{APNS_HOST}/3/device/{device_token}"

    headers = {
        "authorization": f"bearer {token}",
        "apns-topic": APNS_BUNDLE_ID,
        "apns-push-type": "alert",
        "apns-priority": "10",
        "apns-collapse-id": f"friend-request-{sender_id}",  # ← collapses duplicate notifications
    }

    payload = {
        "aps": {
            "alert": {
                "title": title,
                "body": body
            },
            "sound": "default",
            "badge": 1,
            "mutable-content": 1,
            "category": "com.apple.developer.usernotifications.communication"
        },
        "sender_name": sender_name,
        "sender_id": sender_id,
        "conversation_id": conversation_id,
        "notification_id": f"friend-request-{sender_id}",  # ← so iOS side knows what to remove

        **data
    }

    if image_url:
        payload["image_url"] = image_url

    with httpx.Client(http2=True) as client:
        response = client.post(url, json=payload, headers=headers)
        print(f"APNs status: {response.status_code}")
        print(f"APNs response: {response.text}")
        return response.status_code == 200