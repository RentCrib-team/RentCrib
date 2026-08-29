import pytest

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from propertylist_app.models import Notification


pytestmark = pytest.mark.django_db

API_PREFIX = "/api/v1"


def url_notifications_list():
    return f"{API_PREFIX}/notifications/"


def test_notifications_list_requires_auth():
    client = APIClient()

    res = client.get(url_notifications_list())

    assert res.status_code in (401, 403)


def test_notifications_list_returns_unread_total_across_pages():
    User = get_user_model()

    user = User.objects.create_user(
        username="notification-owner",
        email="notification-owner@example.com",
        password="pass12345",
    )

    notifications = []

    for index in range(125):
        notifications.append(
            Notification(
                user=user,
                type=Notification.Type.MESSAGE,
                title=f"Notification {index}",
                body="Notification body",
                is_read=index >= 117,
            )
        )

    Notification.objects.bulk_create(notifications)

    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get(
        url_notifications_list(),
        {
            "limit": 100,
            "offset": 0,
        },
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["ok"] is True
    assert len(payload["data"]) == 100
    assert payload["count"] == 125

    # There are 117 unread notifications in total, even though the
    # current page contains only 100 records.
    assert payload["unread_total"] == 117
    assert payload["meta"]["unread_total"] == 117

    # BE-13: every notification defaults to audience="both", so each
    # role-scoped total covers all 117 unread notifications.
    assert payload["unread_total_landlord"] == 117
    assert payload["unread_total_seeker"] == 117
    assert payload["meta"]["unread_total_landlord"] == 117
    assert payload["meta"]["unread_total_seeker"] == 117


def test_notifications_list_role_scoped_unread_totals():
    User = get_user_model()

    user = User.objects.create_user(
        username="notification-role-owner",
        email="notification-role-owner@example.com",
        password="pass12345",
    )

    Notification.objects.bulk_create(
        [
            Notification(
                user=user,
                type=Notification.Type.MESSAGE,
                title="Landlord only",
                body="Notification body",
                is_read=False,
                audience=Notification.Audience.LANDLORD,
            ),
            Notification(
                user=user,
                type=Notification.Type.MESSAGE,
                title="Seeker only",
                body="Notification body",
                is_read=False,
                audience=Notification.Audience.SEEKER,
            ),
            Notification(
                user=user,
                type=Notification.Type.MESSAGE,
                title="Both roles",
                body="Notification body",
                is_read=False,
                audience=Notification.Audience.BOTH,
            ),
            Notification(
                user=user,
                type=Notification.Type.MESSAGE,
                title="Read landlord",
                body="Notification body",
                is_read=True,
                audience=Notification.Audience.LANDLORD,
            ),
        ]
    )

    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get(
        url_notifications_list(),
        {
            "limit": 100,
            "offset": 0,
        },
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["ok"] is True
    assert payload["unread_total"] == 3

    # Landlord scope: landlord-only + both = 2.
    assert payload["unread_total_landlord"] == 2
    assert payload["meta"]["unread_total_landlord"] == 2

    # Seeker scope: seeker-only + both = 2.
    assert payload["unread_total_seeker"] == 2
    assert payload["meta"]["unread_total_seeker"] == 2

    # The payload exposes the backend audience for each notification.
    audiences_by_title = {
        item["title"]: item["audience"]
        for item in payload["data"]
        if item["title"] in {"Landlord only", "Seeker only", "Both roles", "Read landlord"}
    }

    assert audiences_by_title == {
        "Landlord only": "landlord",
        "Seeker only": "seeker",
        "Both roles": "both",
        "Read landlord": "landlord",
    }