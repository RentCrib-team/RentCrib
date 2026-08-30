import pytest

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from propertylist_app.models import Notification, UserProfile


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
    
def test_notifications_list_is_scoped_to_active_landlord_role():
    User = get_user_model()

    user = User.objects.create_user(
        username="notification-landlord",
        email="notification-landlord@example.com",
        password="pass12345",
    )

    profile, _ = UserProfile.objects.get_or_create(
        user=user
    )
    profile.role = "landlord"
    profile.save(update_fields=["role"])

    landlord_notification = Notification.objects.create(
        user=user,
        type=Notification.Type.MESSAGE,
        audience=Notification.Audience.LANDLORD,
        title="Landlord notification",
        body="Landlord body",
        is_read=False,
    )
    both_notification = Notification.objects.create(
        user=user,
        type=Notification.Type.MESSAGE,
        audience=Notification.Audience.BOTH,
        title="Both notification",
        body="Both body",
        is_read=False,
    )
    seeker_notification = Notification.objects.create(
        user=user,
        type=Notification.Type.MESSAGE,
        audience=Notification.Audience.SEEKER,
        title="Seeker notification",
        body="Seeker body",
        is_read=False,
    )

    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get(url_notifications_list())

    assert response.status_code == 200

    payload = response.json()
    returned_ids = {
        notification["id"]
        for notification in payload["data"]
    }

    assert landlord_notification.id in returned_ids
    assert both_notification.id in returned_ids
    assert seeker_notification.id not in returned_ids
    assert payload["count"] == 2
    assert payload["unread_total"] == 2
    assert payload["meta"]["unread_total"] == 2

    returned_by_id = {
        notification["id"]: notification
        for notification in payload["data"]
    }
    assert (
        returned_by_id[landlord_notification.id]["audience"]
        == Notification.Audience.LANDLORD
    )
    assert (
        returned_by_id[both_notification.id]["audience"]
        == Notification.Audience.BOTH
    )


def test_notifications_list_is_scoped_to_active_seeker_role():
    User = get_user_model()

    user = User.objects.create_user(
        username="notification-seeker",
        email="notification-seeker@example.com",
        password="pass12345",
    )

    profile, _ = UserProfile.objects.get_or_create(
        user=user
    )
    profile.role = "seeker"
    profile.save(update_fields=["role"])

    landlord_notification = Notification.objects.create(
        user=user,
        type=Notification.Type.MESSAGE,
        audience=Notification.Audience.LANDLORD,
        title="Landlord notification",
        body="Landlord body",
        is_read=False,
    )
    both_notification = Notification.objects.create(
        user=user,
        type=Notification.Type.MESSAGE,
        audience=Notification.Audience.BOTH,
        title="Both notification",
        body="Both body",
        is_read=False,
    )
    seeker_notification = Notification.objects.create(
        user=user,
        type=Notification.Type.MESSAGE,
        audience=Notification.Audience.SEEKER,
        title="Seeker notification",
        body="Seeker body",
        is_read=False,
    )

    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get(url_notifications_list())

    assert response.status_code == 200

    payload = response.json()
    returned_ids = {
        notification["id"]
        for notification in payload["data"]
    }

    assert seeker_notification.id in returned_ids
    assert both_notification.id in returned_ids
    assert landlord_notification.id not in returned_ids
    assert payload["count"] == 2
    assert payload["unread_total"] == 2
    assert payload["meta"]["unread_total"] == 2


def test_notifications_switching_role_changes_visibility_without_deleting():
    User = get_user_model()

    user = User.objects.create_user(
        username="notification-role-switch",
        email="notification-role-switch@example.com",
        password="pass12345",
    )

    landlord_notification = Notification.objects.create(
        user=user,
        type=Notification.Type.MESSAGE,
        audience=Notification.Audience.LANDLORD,
        title="Landlord notification",
        body="Landlord body",
        is_read=False,
    )
    seeker_notification = Notification.objects.create(
        user=user,
        type=Notification.Type.MESSAGE,
        audience=Notification.Audience.SEEKER,
        title="Seeker notification",
        body="Seeker body",
        is_read=False,
    )

    profile, _ = UserProfile.objects.get_or_create(
        user=user
    )
    profile.role = "landlord"
    profile.save(update_fields=["role"])

    client = APIClient()
    client.force_authenticate(user=user)

    landlord_response = client.get(url_notifications_list())
    assert landlord_response.status_code == 200

    landlord_ids = {
        notification["id"]
        for notification in landlord_response.json()["data"]
    }

    assert landlord_notification.id in landlord_ids
    assert seeker_notification.id not in landlord_ids

    profile.role = "seeker"
    profile.save(update_fields=["role"])

    seeker_response = client.get(url_notifications_list())
    assert seeker_response.status_code == 200

    seeker_ids = {
        notification["id"]
        for notification in seeker_response.json()["data"]
    }

    assert seeker_notification.id in seeker_ids
    assert landlord_notification.id not in seeker_ids

    assert Notification.objects.filter(
        pk=landlord_notification.pk
    ).exists()
    assert Notification.objects.filter(
        pk=seeker_notification.pk
    ).exists()    
    
def test_notification_mark_read_rejects_other_active_role():
    User = get_user_model()

    user = User.objects.create_user(
        username="notification-mark-read-role",
        email="notification-mark-read-role@example.com",
        password="pass12345",
    )

    profile, _ = UserProfile.objects.get_or_create(
        user=user
    )
    profile.role = "landlord"
    profile.save(update_fields=["role"])

    landlord_notification = Notification.objects.create(
        user=user,
        type=Notification.Type.MESSAGE,
        audience=Notification.Audience.LANDLORD,
        title="Landlord notification",
        body="Landlord body",
        is_read=False,
    )
    both_notification = Notification.objects.create(
        user=user,
        type=Notification.Type.MESSAGE,
        audience=Notification.Audience.BOTH,
        title="Both notification",
        body="Both body",
        is_read=False,
    )
    seeker_notification = Notification.objects.create(
        user=user,
        type=Notification.Type.MESSAGE,
        audience=Notification.Audience.SEEKER,
        title="Seeker notification",
        body="Seeker body",
        is_read=False,
    )

    client = APIClient()
    client.force_authenticate(user=user)

    landlord_response = client.post(
        f"{API_PREFIX}/notifications/{landlord_notification.id}/read/"
    )
    both_response = client.post(
        f"{API_PREFIX}/notifications/{both_notification.id}/read/"
    )
    seeker_response = client.post(
        f"{API_PREFIX}/notifications/{seeker_notification.id}/read/"
    )

    assert landlord_response.status_code == 200
    assert both_response.status_code == 200
    assert seeker_response.status_code == 404

    landlord_notification.refresh_from_db()
    both_notification.refresh_from_db()
    seeker_notification.refresh_from_db()

    assert landlord_notification.is_read is True
    assert both_notification.is_read is True
    assert seeker_notification.is_read is False


def test_notification_mark_all_read_is_scoped_to_active_role():
    User = get_user_model()

    user = User.objects.create_user(
        username="notification-mark-all-role",
        email="notification-mark-all-role@example.com",
        password="pass12345",
    )

    profile, _ = UserProfile.objects.get_or_create(
        user=user
    )
    profile.role = "landlord"
    profile.save(update_fields=["role"])

    landlord_notification = Notification.objects.create(
        user=user,
        type=Notification.Type.MESSAGE,
        audience=Notification.Audience.LANDLORD,
        title="Landlord notification",
        body="Landlord body",
        is_read=False,
    )
    both_notification = Notification.objects.create(
        user=user,
        type=Notification.Type.MESSAGE,
        audience=Notification.Audience.BOTH,
        title="Both notification",
        body="Both body",
        is_read=False,
    )
    seeker_notification = Notification.objects.create(
        user=user,
        type=Notification.Type.MESSAGE,
        audience=Notification.Audience.SEEKER,
        title="Seeker notification",
        body="Seeker body",
        is_read=False,
    )

    client = APIClient()
    client.force_authenticate(user=user)

    response = client.post(
        f"{API_PREFIX}/notifications/read/all/"
    )

    assert response.status_code == 200

    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["marked"] == 2

    landlord_notification.refresh_from_db()
    both_notification.refresh_from_db()
    seeker_notification.refresh_from_db()

    assert landlord_notification.is_read is True
    assert both_notification.is_read is True
    assert seeker_notification.is_read is False    