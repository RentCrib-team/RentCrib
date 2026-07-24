


# They prove:

# reset request works
# no email enumeration leak
# reset OTP is hashed
# correct token changes password
# wrong token increments attempts









import pytest
from django.contrib.auth import authenticate, get_user_model
from django.urls import reverse

from rest_framework.settings import api_settings


from propertylist_app.models import EmailOTP
from django.core.cache import caches
pytestmark = pytest.mark.django_db


def make_user():
    return get_user_model().objects.create_user(
        username="resetuser",
        email="resetuser@example.com",
        password="OldPass1!",
    )


def test_password_reset_request_creates_hashed_otp(api_client):
    user = make_user()
    url = reverse("api:auth-password-reset")

    response = api_client.post(url, {"email": user.email}, format="json")

    assert response.status_code == 200, response.json()

    otp = EmailOTP.objects.filter(
        user=user,
        purpose=EmailOTP.PURPOSE_PASSWORD_RESET,
        used_at__isnull=True,
    ).latest("created_at")

    assert len(otp.code) > 20


def test_password_reset_request_nonexistent_email_is_generic(api_client):
    url = reverse("api:auth-password-reset")

    response = api_client.post(url, {"email": "nobody@example.com"}, format="json")

    assert response.status_code == 200, response.json()


def test_password_reset_confirm_changes_password(api_client):
    user = make_user()
    EmailOTP.create_for(
        user,
        "123456",
        ttl_minutes=10,
        purpose=EmailOTP.PURPOSE_PASSWORD_RESET,
    )

    url = reverse("api:auth-password-reset-confirm")
    response = api_client.post(
        url,
        {
            "email": user.email,
            "token": "123456",
            "new_password": "NewPass1!",
            "confirm_password": "NewPass1!",
        },
        format="json",
    )

    assert response.status_code == 200, response.json()

    user.refresh_from_db()
    assert authenticate(username=user.username, password="OldPass1!") is None
    assert authenticate(username=user.username, password="NewPass1!") is not None


def test_password_reset_confirm_wrong_token_increments_attempts(api_client):
    user = make_user()
    otp = EmailOTP.create_for(
        user,
        "123456",
        ttl_minutes=10,
        purpose=EmailOTP.PURPOSE_PASSWORD_RESET,
    )

    url = reverse("api:auth-password-reset-confirm")
    response = api_client.post(
        url,
        {
            "email": user.email,
            "token": "000000",
            "new_password": "NewPass1!",
            "confirm_password": "NewPass1!",
        },
        format="json",
    )

    assert response.status_code == 400, response.json()

    otp.refresh_from_db()
    assert otp.attempts == 1
    assert otp.used_at is None
    
    
    
def test_password_reset_request_is_throttled_after_three_requests(
    api_client,
    settings,
    monkeypatch,
):
    """
    Password-reset requests are limited by IP.

    The first three requests are allowed.
    The fourth request from the same IP must return HTTP 429.
    """
    monkeypatch.setitem(
        settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
        "password-reset",
        "3/hour",
    )

    api_settings.reload()
    caches["default"].clear()

    url = reverse("api:auth-password-reset")
    request_ip = "203.0.113.90"

    for index in range(3):
        response = api_client.post(
            url,
            {"email": f"reset-target-{index}@example.com"},
            format="json",
            REMOTE_ADDR=request_ip,
        )

        assert response.status_code == 200, response.json()

    throttled_response = api_client.post(
        url,
        {"email": "reset-target-4@example.com"},
        format="json",
        REMOTE_ADDR=request_ip,
    )

    assert throttled_response.status_code == 429, throttled_response.json()