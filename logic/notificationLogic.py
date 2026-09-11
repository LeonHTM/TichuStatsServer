import jwt
import time
import httpx
from logic.profileLogic import UserDeviceToken, FriendRequest
from config import (
    APNS_TEAM_ID,
    APNS_KEY,
    APNS_KEY_ID,
    APNS_BUNDLE_ID,
    APNS_HOST
)


_cached_token = None
_cached_token_time = 0
_TOKEN_TTL_SECONDS = 55 * 60


def get_apns_token():
    global _cached_token, _cached_token_time

    now = int(time.time())
    if _cached_token and (now - _cached_token_time) < _TOKEN_TTL_SECONDS:
        return _cached_token

    payload = {
        "iss": APNS_TEAM_ID,
        "iat": now
    }

    _cached_token = jwt.encode(
        payload,
        APNS_KEY,
        algorithm="ES256",
        headers={"kid": APNS_KEY_ID}
    )
    _cached_token_time = now
    return _cached_token


def get_pending_request_count(profile_id: int) -> int:
    return FriendRequest.query.filter_by(receiver_id=profile_id, status="pending").count()


def build_alert(
    title_loc_key: str,
    loc_key: str,
    title_loc_args: list = None,
    loc_args: list = None,
):

    return {
        "title-loc-key": title_loc_key,
        "title-loc-args": title_loc_args or [],
        "loc-key": loc_key,
        "loc-args": loc_args or [],
    }


def _log_apns_debug(device_token: str, response: httpx.Response):
    # Helpful when diagnosing BadDeviceToken: confirms exactly what host,
    # topic, and token prefix were used for this request.
    token_preview = f"{device_token[:8]}...{device_token[-4:]}" if len(device_token) > 12 else device_token
    print(f"APNs host: {APNS_HOST}")
    print(f"APNs topic: {APNS_BUNDLE_ID}")
    print(f"APNs device token: {token_preview} (len={len(device_token)})")
    print(f"APNs status: {response.status_code}")
    print(f"APNs response: {response.text}")


def send_push_notification(
    device_token: str,
    sender_name: str,
    sender_id: str,
    receiver_id: str,
    conversation_id: str,
    title_loc_key: str,
    loc_key: str,
    title_loc_args: list = None,
    loc_args: list = None,
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
        "apns-collapse-id": f"friend-request-{sender_id}",
    }

    badge_count = get_pending_request_count(int(receiver_id))

    payload = {
        "aps": {
            "alert": build_alert(
                title_loc_key=title_loc_key,
                loc_key=loc_key,
                title_loc_args=title_loc_args,
                loc_args=loc_args,
            ),
            "sound": "default",
            "badge": badge_count,
            "mutable-content": 1,
            "category": "com.apple.developer.usernotifications.communication"
        },
        "sender_name": sender_name,
        "sender_id": sender_id,
        "conversation_id": conversation_id,
        "notification_id": f"friend-request-{sender_id}",

        **data
    }

    if image_url:
        payload["image_url"] = image_url

    with httpx.Client(http2=True) as client:
        response = client.post(url, json=payload, headers=headers)
        #_log_apns_debug(device_token, response)
        return response.status_code == 200


def send_accepted_notification(
    device_token: str,
    sender_name: str,
    sender_id: str,
    receiver_id: str,
    conversation_id: str,
    title_loc_key: str,
    loc_key: str,
    title_loc_args: list = None,
    loc_args: list = None,
    image_url: str = None,
):
    token = get_apns_token()
    url = f"https://{APNS_HOST}/3/device/{device_token}"

    headers = {
        "authorization": f"bearer {token}",
        "apns-topic": APNS_BUNDLE_ID,
        "apns-push-type": "alert",
        "apns-priority": "10",
        "apns-collapse-id": f"friend-request-accepted-{receiver_id}",
    }

    badge_count = get_pending_request_count(int(sender_id))

    payload = {
        "aps": {
            "alert": build_alert(
                title_loc_key=title_loc_key,
                loc_key=loc_key,
                title_loc_args=title_loc_args,
                loc_args=loc_args,
            ),
            "sound": "default",
            "badge": badge_count,
            "mutable-content": 1,
            "category": "com.apple.developer.usernotifications.communication"
        },
        "sender_name": sender_name,
        "sender_id": sender_id,
        "conversation_id": conversation_id,
        "notification_id": f"friend-request-accepted-{receiver_id}",
    }

    if image_url:
        payload["image_url"] = image_url

    with httpx.Client(http2=True) as client:
        response = client.post(url, json=payload, headers=headers)
        _log_apns_debug(device_token, response)
        return response.status_code == 200


def send_push_notifications_to_user(
    device_tokens: list[str],
    sender_name: str,
    sender_id: str,
    receiver_id: str,
    conversation_id: str,
    title_loc_key: str,
    loc_key: str,
    title_loc_args: list = None,
    loc_args: list = None,
    image_url: str = None,
    data: dict = {}
):
    results = []
    for token in device_tokens:
        result = send_push_notification(
            device_token=token,
            sender_name=sender_name,
            sender_id=sender_id,
            receiver_id=receiver_id,
            conversation_id=conversation_id,
            title_loc_key=title_loc_key,
            loc_key=loc_key,
            title_loc_args=title_loc_args,
            loc_args=loc_args,
            image_url=image_url,
            data=data
        )
        results.append(result)
    return all(results)


def notify_accepted(profile_id: int, sender_name: str, sender_id: str,
                    conversation_id: str, title_loc_key: str, loc_key: str,
                    title_loc_args: list = None, loc_args: list = None,
                    image_url: str = None):
    tokens = get_device_tokens(profile_id)
    for token in tokens:
        send_accepted_notification(
            device_token=token,
            sender_name=sender_name,
            sender_id=sender_id,
            receiver_id=str(profile_id),
            conversation_id=conversation_id,
            title_loc_key=title_loc_key,
            loc_key=loc_key,
            title_loc_args=title_loc_args,
            loc_args=loc_args,
            image_url=image_url
        )


# Helper to get all tokens for a user
def get_device_tokens(profile_id: int) -> list[str]:
    tokens = UserDeviceToken.query.filter_by(user_id=profile_id).all()
    return [t.device_token for t in tokens]


# Helper to notify a user on all devices
def notify_user(profile_id: int, sender_name: str, sender_id: str,
                conversation_id: str, title_loc_key: str, loc_key: str,
                title_loc_args: list = None, loc_args: list = None,
                image_url: str = None):
    tokens = get_device_tokens(profile_id)
    if tokens:
        send_push_notifications_to_user(
            device_tokens=tokens,
            sender_name=sender_name,
            sender_id=sender_id,
            receiver_id=str(profile_id),
            conversation_id=conversation_id,
            title_loc_key=title_loc_key,
            loc_key=loc_key,
            title_loc_args=title_loc_args,
            loc_args=loc_args,
            image_url=image_url
        )