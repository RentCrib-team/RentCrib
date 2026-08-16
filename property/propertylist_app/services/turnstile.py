import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def verify_turnstile(token: str, ip: str = None) -> bool:
    if not token:
        logger.warning("Turnstile verification attempted without a token")
        return False

    data = {
        "secret": settings.TURNSTILE_SECRET_KEY,
        "response": token,
    }

    if ip:
        data["remoteip"] = ip

    try:
        response = requests.post(
            TURNSTILE_VERIFY_URL,
            data=data,
            timeout=5,
        )
        response.raise_for_status()

        result = response.json()
        success = bool(result.get("success", False))

        if not success:
            logger.warning(
                "Turnstile verification failed: error_codes=%s hostname=%s action=%s",
                result.get("error-codes", []),
                result.get("hostname"),
                result.get("action"),
            )

        return success

    except requests.RequestException:
        logger.exception("Turnstile verification request failed")
        return False

    except ValueError:
        logger.exception("Turnstile verification returned invalid JSON")
        return False
