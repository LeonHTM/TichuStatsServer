import jwt
import time
import httpx




from config import APNS_TEAM_ID,APNS_KEY,APNS_KEY_ID,APNS_BUNDLE_ID
DEVICE_TOKEN = "421d8d4227aa86a19295a6f9bdc969d063e9c24c2d7edafa38b5ba20d500e898"

# Change to "api.push.apple.com" if testing with TestFlight/production
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

token = get_apns_token()
url = f"https://{APNS_HOST}/3/device/{DEVICE_TOKEN}"

headers = {
    "authorization": f"bearer {token}",
    "apns-topic": APNS_BUNDLE_ID,
    "apns-push-type": "alert",
    "apns-priority": "10",
}

payload = {
    "aps": {
        "alert": {
            "title": "Test",
            "body": "Hello from Tichu!"
        },
        "sound": "default"
    }
}

with httpx.Client(http2=True) as client:
    response = client.post(url, json=payload, headers=headers)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")