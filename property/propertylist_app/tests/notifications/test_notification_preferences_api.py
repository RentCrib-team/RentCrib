import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


pytestmark = pytest.mark.django_db

User = get_user_model()

API_PREFIX = "/api/v1"


def make_user(email: str):
    username = email.split("@")[0]
    return User.objects.create_user(
        username=username,
        email=email,
        password="pass12345",
    )


def auth_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def url_my_notification_preferences():
    return f"{API_PREFIX}/users/me/notification-preferences/"


def response_body(response):
    return response.data.get("data", response.data)


def response_field_errors(response):
    return (
        response.data.get("field_errors")
        or response.data.get("details")
        or response.data
    )


def test_notification_preferences_get_requires_auth():
    client = APIClient()

    response = client.get(url_my_notification_preferences())

    assert response.status_code in (401, 403)


def test_notification_preferences_get_returns_all_supported_preferences():
    user = make_user("preferences_get@example.com")
    client = auth_client(user)

    response = client.get(url_my_notification_preferences())

    assert response.status_code == 200, getattr(response, "data", None)

    body = response_body(response)

    expected_fields = {
        "marketing_consent",
        "theme",
        "date_format",
        "time_format",
        "notify_email",
        "notify_push",
        "notify_sms",
        "notify_rentout_updates",
        "notify_reminders",
        "notify_messages",
        "notify_confirmations",
        "notify_weekly_reports",
        "notify_monthly_reports",
        "notify_system_alerts",
        "notify_user_reports",
        "notify_payment_alerts",
    }

    assert expected_fields.issubset(body.keys())


def test_notification_preferences_patch_updates_preferences():
    user = make_user("preferences_patch@example.com")
    client = auth_client(user)

    payload = {
        "theme": "dark",
        "date_format": "YYYY-MM-DD",
        "time_format": "12h",
        "notify_email": False,
        "notify_push": True,
        "notify_sms": True,
        "notify_rentout_updates": False,
        "notify_reminders": True,
        "notify_messages": False,
        "notify_confirmations": True,
        "notify_weekly_reports": False,
        "notify_monthly_reports": True,
        "notify_system_alerts": False,
        "notify_user_reports": True,
        "notify_payment_alerts": False,
    }

    response = client.patch(
        url_my_notification_preferences(),
        data=payload,
        format="json",
    )

    assert response.status_code == 200, getattr(response, "data", None)

    body = response_body(response)

    for field, expected_value in payload.items():
        assert body[field] == expected_value

    user.profile.refresh_from_db()

    for field, expected_value in payload.items():
        assert getattr(user.profile, field) == expected_value


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("theme", "neon"),
        ("date_format", "DAY-MONTH-YEAR"),
        ("time_format", "evening"),
    ],
)
def test_notification_preferences_patch_rejects_invalid_choice(
    field,
    invalid_value,
):
    user = make_user(f"invalid_{field}@example.com")
    client = auth_client(user)

    response = client.patch(
        url_my_notification_preferences(),
        data={field: invalid_value},
        format="json",
    )

    assert response.status_code == 400, getattr(response, "data", None)

    errors = response_field_errors(response)
    assert field in errors