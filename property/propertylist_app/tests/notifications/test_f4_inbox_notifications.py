import pytest
from django.urls import reverse
from rest_framework.test import APIClient




from propertylist_app.models import (
    Message,
    MessageRead,
    MessageThread,
    Notification,
    UserProfile,
)



@pytest.mark.django_db
def test_f4_inbox_includes_only_my_notifications(user_factory):
    """
    F4 backend readiness:
    - /api/v1/inbox/ returns notifications + threads merged
    - notifications are scoped to request.user only
    """
    client = APIClient()

    user_a = user_factory(username="user_a", email="a@example.com")
    user_b = user_factory(username="user_b", email="b@example.com")

    # Create notifications for both users
    n_a1 = Notification.objects.create(
        user=user_a,
        type="confirmation",
        title="A1",
        body="Hello A",
        is_read=False,
    )
    Notification.objects.create(
        user=user_b,
        type="confirmation",
        title="B1",
        body="Hello B",
        is_read=False,
    )

    client.force_authenticate(user=user_a)

    url = reverse("api:inbox-list")
    resp = client.get(url)

    assert resp.status_code == 200
    assert resp.data.get("ok") is True

    items = resp.data.get("data") or []
    assert isinstance(items, list)

    # Only user_a's notification should appear
    notif_ids = [i.get("notification_id") for i in items if i.get("kind") == "notification"]
    assert n_a1.id in notif_ids
    assert all(nid != 0 for nid in notif_ids if nid is not None)

    # Ensure no leakage from user_b
    assert Notification.objects.filter(user=user_b).first().id not in notif_ids
    
    
    

@pytest.mark.django_db
def test_f4_notification_mark_read_is_user_scoped(user_factory):
    client = APIClient()

    user_a = user_factory(username="user_a2", email="a2@example.com")
    user_b = user_factory(username="user_b2", email="b2@example.com")

    n_b = Notification.objects.create(
        user=user_b,
        type="confirmation",
        title="B only",
        body="Private",
        is_read=False,
    )

    client.force_authenticate(user=user_a)

    url = reverse("api:notification-mark-read", kwargs={"pk": n_b.id})
    resp = client.post(url)

    # get_object_or_404(Notification, pk=pk, user=request.user) => 404 for other users
    assert resp.status_code == 404

    n_b.refresh_from_db()
    assert n_b.is_read is False
    
    


@pytest.mark.django_db
def test_f4_notifications_list_orders_unread_first(user_factory):
    client = APIClient()
    user = user_factory(username="u_notifs", email="u_notifs@example.com")
    client.force_authenticate(user=user)

    # Create read + unread
    n_read = Notification.objects.create(
        user=user, type="confirmation", title="Read", body="r", is_read=True
    )
    n_unread = Notification.objects.create(
        user=user, type="confirmation", title="Unread", body="u", is_read=False
    )

    url = reverse("api:notifications-list")
    resp = client.get(url)

    assert resp.status_code == 200
    data = resp.data.get("data", resp.data)
    assert isinstance(data, list)
    assert len(data) >= 2

    # First item should be unread (is_read False comes first)
    assert data[0]["is_read"] is False
    ids = [row["id"] for row in data]
    assert n_unread.id in ids and n_read.id in ids    
    
@pytest.mark.django_db
def test_f4_inbox_avoids_per_thread_queries(
    user_factory,
    django_assert_max_num_queries,
):
    client = APIClient()

    user = user_factory(
        username="inbox_query_owner",
        email="inbox-query-owner@example.com",
    )
    other_user = user_factory(
        username="inbox_query_contact",
        email="inbox-query-contact@example.com",
    )

    expected_latest_bodies = set()

    for thread_number in range(8):
        thread = MessageThread.objects.create()
        thread.participants.set([user, other_user])

        for message_number in range(10):
            body = (
                f"Thread {thread_number} "
                f"message {message_number}"
            )

            Message.objects.create(
                thread=thread,
                sender=(
                    user
                    if message_number % 2 == 0
                    else other_user
                ),
                body=body,
                metadata={
                    "system_event": True,
                },
            )

        expected_latest_bodies.add(
            f"Thread {thread_number} message 9"
        )

    client.force_authenticate(user=user)
    url = reverse("api:inbox-list")

    # Warm up framework rendering before measuring queries.
    warmup = client.get(url, {"limit": 100})
    assert warmup.status_code == 200

    with django_assert_max_num_queries(10):
        response = client.get(
            url,
            {
                "limit": 100,
            },
        )

    assert response.status_code == 200

    items = response.data.get("data") or []

    thread_previews = {
        item["preview"]
        for item in items
        if item.get("kind") == "thread"
    }

    assert thread_previews == expected_latest_bodies


@pytest.mark.django_db
def test_message_stats_counts_system_messages_consistently(
    user_factory,
):
    client = APIClient()

    user = user_factory(
        username="stats_owner",
        email="stats-owner@example.com",
    )
    other_user = user_factory(
        username="stats_contact",
        email="stats-contact@example.com",
    )

    thread = MessageThread.objects.create()
    thread.participants.set([user, other_user])

    # A system message may use the current user as its database sender,
    # but it must remain unread until that user opens it.
    system_message = Message.objects.create(
        thread=thread,
        sender=user,
        body="RentCrib system update",
        metadata={
            "system_event": True,
        },
    )

    client.force_authenticate(user=user)
    url = reverse("api:messages-stats")

    unread_response = client.get(url)
    assert unread_response.status_code == 200

    unread_payload = unread_response.data
    unread_stats = unread_payload.get(
        "data",
        unread_payload,
    )

    assert unread_stats["total_unread"] == 1

    MessageRead.objects.create(
        message=system_message,
        user=user,
    )

    read_response = client.get(url)
    assert read_response.status_code == 200

    read_payload = read_response.data
    read_stats = read_payload.get(
        "data",
        read_payload,
    )

    assert read_stats["total_unread"] == 0    
    
    
@pytest.mark.django_db
def test_f4_inbox_is_partitioned_by_active_role(
    user_factory,
):
    client = APIClient()

    user = user_factory(
        username="dual_role_inbox_user",
        email="dual-role-inbox@example.com",
    )
    landlord_contact = user_factory(
        username="landlord_side_contact",
        email="landlord-side@example.com",
    )
    seeker_contact = user_factory(
        username="seeker_side_contact",
        email="seeker-side@example.com",
    )
    legacy_contact = user_factory(
        username="legacy_side_contact",
        email="legacy-side@example.com",
    )

    profile, _ = UserProfile.objects.get_or_create(
        user=user
    )

    landlord_notification = Notification.objects.create(
        user=user,
        type="confirmation",
        title="Landlord notification",
        body="Landlord only",
        audience=Notification.Audience.LANDLORD,
        is_read=False,
    )
    seeker_notification = Notification.objects.create(
        user=user,
        type="confirmation",
        title="Seeker notification",
        body="Seeker only",
        audience=Notification.Audience.SEEKER,
        is_read=False,
    )
    both_notification = Notification.objects.create(
        user=user,
        type="confirmation",
        title="Both notification",
        body="Both roles",
        audience=Notification.Audience.BOTH,
        is_read=False,
    )

    landlord_thread = MessageThread.objects.create(
        landlord=user,
        seeker=landlord_contact,
    )
    landlord_thread.participants.set(
        [user, landlord_contact]
    )
    Message.objects.create(
        thread=landlord_thread,
        sender=landlord_contact,
        body="Landlord thread message",
    )

    seeker_thread = MessageThread.objects.create(
        landlord=seeker_contact,
        seeker=user,
    )
    seeker_thread.participants.set(
        [user, seeker_contact]
    )
    Message.objects.create(
        thread=seeker_thread,
        sender=seeker_contact,
        body="Seeker thread message",
    )

    legacy_thread = MessageThread.objects.create()
    legacy_thread.participants.set(
        [user, legacy_contact]
    )
    Message.objects.create(
        thread=legacy_thread,
        sender=legacy_contact,
        body="Legacy thread message",
    )

    client.force_authenticate(user=user)
    url = reverse("api:inbox-list")

    # Landlord mode
    profile.role = "landlord"
    profile.save(update_fields=["role"])

    landlord_response = client.get(
        url,
        {"limit": 100},
    )
    assert landlord_response.status_code == 200

    landlord_items = landlord_response.data.get("data") or []

    landlord_notification_ids = {
        item.get("notification_id")
        for item in landlord_items
        if item.get("kind") == "notification"
    }
    landlord_thread_ids = {
        item.get("thread_id")
        for item in landlord_items
        if item.get("kind") == "thread"
    }

    assert landlord_notification.id in landlord_notification_ids
    assert both_notification.id in landlord_notification_ids
    assert seeker_notification.id not in landlord_notification_ids

    assert landlord_thread.id in landlord_thread_ids
    assert legacy_thread.id in landlord_thread_ids
    assert seeker_thread.id not in landlord_thread_ids

    # Seeker mode
    profile.role = "seeker"
    profile.save(update_fields=["role"])

    seeker_response = client.get(
        url,
        {"limit": 100},
    )
    assert seeker_response.status_code == 200

    seeker_items = seeker_response.data.get("data") or []

    seeker_notification_ids = {
        item.get("notification_id")
        for item in seeker_items
        if item.get("kind") == "notification"
    }
    seeker_thread_ids = {
        item.get("thread_id")
        for item in seeker_items
        if item.get("kind") == "thread"
    }

    assert seeker_notification.id in seeker_notification_ids
    assert both_notification.id in seeker_notification_ids
    assert landlord_notification.id not in seeker_notification_ids

    assert seeker_thread.id in seeker_thread_ids
    assert legacy_thread.id in seeker_thread_ids
    assert landlord_thread.id not in seeker_thread_ids

    # Switching roles only changes visibility.
    # Nothing is deleted.
    assert Notification.objects.filter(
        id__in=[
            landlord_notification.id,
            seeker_notification.id,
            both_notification.id,
        ]
    ).count() == 3

    assert MessageThread.objects.filter(
        id__in=[
            landlord_thread.id,
            seeker_thread.id,
            legacy_thread.id,
        ]
    ).count() == 3    