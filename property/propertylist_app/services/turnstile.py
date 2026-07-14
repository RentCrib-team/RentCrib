import requests
from django.conf import settings

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

def verify_turnstile(token: str, ip: str = None) -> bool:
    if not token:
        return False

    data = {
        "secret": settings.TURNSTILE_SECRET_KEY,
        "response": token,
    }

    if ip:
        data["remoteip"] = ip

    try:
        response = requests.post(TURNSTILE_VERIFY_URL, data=data, timeout=5)
        result = response.json()
        return result.get("success", False)
    except Exception:
        return False