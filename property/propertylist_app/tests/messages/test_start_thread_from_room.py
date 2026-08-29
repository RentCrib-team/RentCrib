import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie, MessageThread, Message


pytestmark = pytest.mark.django_db


def _mk_user(username: str) -> User:
    return User.objects.create_user(username=username, password="pass12345")


def _mk_room(owner: User, status: str = "active") -> Room:
    cat = RoomCategorie.objects.create(name="General", key=f"general-{owner.username}")
    return Room.objects.create(
        title=f"Room {owner.username}",
        description="desc",
        price_per_month="500.00",
        location="London",
        category=cat,
        property_owner=owner,
        property_type="flat",
        status=status,
    )


def test_start_thread_from_room_happy_path_creates_thread_and_optional_first_message():
    landlord = _mk_user("landlord")
    tenant = _mk_user("tenant")
    room = _mk_room(landlord, status="active")

    client = APIClient()
    client.force_authenticate(user=tenant)

    url = reverse("v1:start-thread-from-room", kwargs={"room_id": room.id})

    r = client.post(url, {"body": "Hello"}, format="json")
    assert r.status_code == 200

    # Thread exists between tenant and landlord
    thread = MessageThread.objects.filter(participants=tenant).filter(participants=landlord).first()
    assert thread is not None
    
    assert thread.landlord_id == landlord.id
    assert thread.seeker_id == tenant.id

    # First message created because body supplied
    assert Message.objects.filter(thread=thread, sender=tenant, body="Hello").exists()


def test_start_thread_from_room_reuses_existing_thread():
    landlord = _mk_user("landlord2")
    tenant = _mk_user("tenant2")
    room = _mk_room(landlord, status="active")

    # Pre-create thread between them
    thread = MessageThread.objects.create()
    thread.participants.set([tenant, landlord])

    client = APIClient()
    client.force_authenticate(user=tenant)

    url = reverse("v1:start-thread-from-room", kwargs={"room_id": room.id})

    r = client.post(url, {"body": "Hi again"}, format="json")
    assert r.status_code == 200
    thread.refresh_from_db()
    assert thread.landlord_id == landlord.id
    assert thread.seeker_id == tenant.id

    # Still only one thread between them
    assert (
        MessageThread.objects.filter(participants=tenant)
        .filter(participants=landlord)
        .distinct()
        .count()
        == 1
    )

    # Message added to existing thread
    assert Message.objects.filter(thread=thread, body="Hi again").exists()


def test_start_thread_from_room_hidden_room_returns_404():
    landlord = _mk_user("landlord3")
    tenant = _mk_user("tenant3")
    room = _mk_room(landlord, status="hidden")  # NOT alive

    client = APIClient()
    client.force_authenticate(user=tenant)

    url = reverse("v1:start-thread-from-room", kwargs={"room_id": room.id})

    r = client.post(url, {"body": "Hello"}, format="json")
    assert r.status_code == 404


def test_start_thread_from_room_anonymous_rejected():
    landlord = _mk_user("landlord4")
    room = _mk_room(landlord, status="active")

    client = APIClient()

    url = reverse("v1:start-thread-from-room", kwargs={"room_id": room.id})

    r = client.post(url, {"body": "Hello"}, format="json")
    assert r.status_code in (401, 403)


def test_start_thread_from_room_owner_cannot_start_thread_with_self():
    landlord = _mk_user("landlord5")
    room = _mk_room(landlord, status="active")

    client = APIClient()
    client.force_authenticate(user=landlord)

    url = reverse("v1:start-thread-from-room", kwargs={"room_id": room.id})

    r = client.post(url, {"body": "Hello"}, format="json")
    assert r.status_code == 400
    assert r.data["detail"] == "You are the owner of this room; no thread needed."
    
    
    
def test_thread_list_uses_authoritative_role_and_context_metadata():
    current_user = _mk_user("role-user")
    landlord_counterpart = _mk_user("role-landlord")
    seeker_counterpart = _mk_user("role-seeker")
    legacy_counterpart = _mk_user("role-legacy")

    # Current user is landlord for this thread.
    landlord_room = _mk_room(current_user, status="active")
    landlord_thread = MessageThread.objects.create(
        room=landlord_room,
        landlord=current_user,
        seeker=seeker_counterpart,
    )
    landlord_thread.participants.set(
        [current_user, seeker_counterpart]
    )

    # Current user is seeker for this thread.
    seeker_room = _mk_room(
        landlord_counterpart,
        status="active",
    )
    seeker_thread = MessageThread.objects.create(
        room=seeker_room,
        landlord=landlord_counterpart,
        seeker=current_user,
    )
    seeker_thread.participants.set(
        [landlord_counterpart, current_user]
    )

    # Historical roomless thread must remain explicitly unscoped.
    legacy_thread = MessageThread.objects.create()
    legacy_thread.participants.set(
        [current_user, legacy_counterpart]
    )

    client = APIClient()
    client.force_authenticate(user=current_user)

    landlord_response = client.get(
        "/api/v1/messages/threads/",
        {"role": "landlord"},
    )
    assert landlord_response.status_code == 200

    landlord_items = landlord_response.data["data"]
    assert [item["id"] for item in landlord_items] == [
        landlord_thread.id
    ]

    landlord_item = landlord_items[0]
    assert landlord_item["participant_role"] == "landlord"
    assert landlord_item["relationship_type"] == "room_enquiry"
    assert landlord_item["room_id"] == landlord_room.id
    assert landlord_item["landlord_id"] == current_user.id
    assert landlord_item["seeker_id"] == seeker_counterpart.id

    seeker_response = client.get(
        "/api/v1/messages/threads/",
        {"role": "seeker"},
    )
    assert seeker_response.status_code == 200

    seeker_items = seeker_response.data["data"]
    assert [item["id"] for item in seeker_items] == [
        seeker_thread.id
    ]

    seeker_item = seeker_items[0]
    assert seeker_item["participant_role"] == "seeker"
    assert seeker_item["relationship_type"] == "room_enquiry"
    assert seeker_item["room_id"] == seeker_room.id
    assert seeker_item["landlord_id"] == landlord_counterpart.id
    assert seeker_item["seeker_id"] == current_user.id

    all_threads_response = client.get(
        "/api/v1/messages/threads/",
    )
    assert all_threads_response.status_code == 200

    all_items = all_threads_response.data["data"]
    all_items_by_id = {
        item["id"]: item
        for item in all_items
    }

    assert set(all_items_by_id) == {
        landlord_thread.id,
        seeker_thread.id,
        legacy_thread.id,
    }

    legacy_item = all_items_by_id[legacy_thread.id]
    assert legacy_item["participant_role"] == "unscoped"
    assert legacy_item["relationship_type"] == "legacy_direct"
    assert legacy_item["room_id"] is None
    assert legacy_item["landlord_id"] is None
    assert legacy_item["seeker_id"] is None

    invalid_response = client.get(
        "/api/v1/messages/threads/",
        {"role": "invalid"},
    )
    assert invalid_response.status_code == 400    
