import pytest
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APIClient
from drf_spectacular.generators import SchemaGenerator
from propertylist_app.models import (
    Room,
    RoomCategorie,
    MessageThread,
    Message,
    UserProfile,
)


pytestmark = pytest.mark.django_db


def _mk_user(username: str) -> User:
    return User.objects.create_user(username=username, password="pass12345")


def _mk_room(
    owner: User,
    status: str = "active",
    key_suffix: str = "",
) -> Room:
    cat = RoomCategorie.objects.create(
        name="General",
        key=f"general-{owner.username}{key_suffix}",
    )

    return Room.objects.create(
        title=f"Room {owner.username}{key_suffix}",
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

    profile, _ = UserProfile.objects.get_or_create(
        user=current_user
    )

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

    # Historical roomless thread remains visible under either active role.
    legacy_thread = MessageThread.objects.create()
    legacy_thread.participants.set(
        [current_user, legacy_counterpart]
    )

    client = APIClient()
    client.force_authenticate(user=current_user)

    # Active landlord role is authoritative.
    profile.role = "landlord"
    profile.save(update_fields=["role"])

    landlord_response = client.get(
        "/api/v1/messages/threads/",
    )

    assert landlord_response.status_code == 200
    landlord_items = landlord_response.data["data"]

    landlord_items_by_id = {
        item["id"]: item
        for item in landlord_items
    }

    assert set(landlord_items_by_id) == {
        landlord_thread.id,
        legacy_thread.id,
    }
    assert seeker_thread.id not in landlord_items_by_id

    landlord_item = landlord_items_by_id[landlord_thread.id]

    assert landlord_item["participant_role"] == "landlord"
    assert landlord_item["inbox_side"] == "landlord"
    assert landlord_item["relationship_type"] == "room_enquiry"
    assert landlord_item["relationship_id"] == landlord_room.id
    assert landlord_item["property_id"] == landlord_room.id
    assert landlord_item["room_id"] == landlord_room.id
    assert landlord_item["landlord_id"] == current_user.id
    assert landlord_item["seeker_id"] == seeker_counterpart.id

    legacy_item = landlord_items_by_id[legacy_thread.id]

    assert legacy_item["participant_role"] == "unscoped"
    assert legacy_item["inbox_side"] == "unscoped"
    assert legacy_item["relationship_type"] == "legacy_direct"
    assert legacy_item["relationship_id"] is None
    assert legacy_item["property_id"] is None
    assert legacy_item["room_id"] is None
    assert legacy_item["landlord_id"] is None
    assert legacy_item["seeker_id"] is None

    # Query parameter cannot bypass the persisted active role.
    landlord_with_seeker_param = client.get(
        "/api/v1/messages/threads/",
        {"role": "seeker"},
    )

    assert landlord_with_seeker_param.status_code == 200

    landlord_with_seeker_param_ids = {
        item["id"]
        for item in landlord_with_seeker_param.data["data"]
    }

    assert landlord_with_seeker_param_ids == {
        landlord_thread.id,
        legacy_thread.id,
    }
    assert seeker_thread.id not in landlord_with_seeker_param_ids

    # Switching the persisted role changes visibility without deleting threads.
    profile.role = "seeker"
    profile.save(update_fields=["role"])

    seeker_response = client.get(
        "/api/v1/messages/threads/",
    )

    assert seeker_response.status_code == 200
    seeker_items = seeker_response.data["data"]

    seeker_items_by_id = {
        item["id"]: item
        for item in seeker_items
    }

    assert set(seeker_items_by_id) == {
        seeker_thread.id,
        legacy_thread.id,
    }
    assert landlord_thread.id not in seeker_items_by_id

    seeker_item = seeker_items_by_id[seeker_thread.id]

    assert seeker_item["participant_role"] == "seeker"
    assert seeker_item["inbox_side"] == "seeker"
    assert seeker_item["relationship_type"] == "room_enquiry"
    assert seeker_item["relationship_id"] == seeker_room.id
    assert seeker_item["property_id"] == seeker_room.id
    assert seeker_item["room_id"] == seeker_room.id
    assert seeker_item["landlord_id"] == landlord_counterpart.id
    assert seeker_item["seeker_id"] == current_user.id

    assert MessageThread.objects.filter(
        pk=landlord_thread.pk
    ).exists()
    assert MessageThread.objects.filter(
        pk=seeker_thread.pk
    ).exists()
    assert MessageThread.objects.filter(
        pk=legacy_thread.pk
    ).exists()

    # Existing API validation remains intact.
    invalid_response = client.get(
        "/api/v1/messages/threads/",
        {"role": "invalid"},
    )

    assert invalid_response.status_code == 400
    
def test_same_pair_different_rooms_keep_distinct_context():
    landlord = _mk_user("context-landlord")
    seeker = _mk_user("context-seeker")

    first_room = _mk_room(
    landlord,
    key_suffix="-a",
    )

    second_room = _mk_room(
        landlord,
        key_suffix="-b",
    )

    client = APIClient()
    client.force_authenticate(user=seeker)

    first_response = client.post(
        reverse(
            "v1:start-thread-from-room",
            kwargs={"room_id": first_room.id},
        ),
        {},
        format="json",
    )
    second_response = client.post(
        reverse(
            "v1:start-thread-from-room",
            kwargs={"room_id": second_room.id},
        ),
        {},
        format="json",
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200

    first_item = first_response.data["data"]
    second_item = second_response.data["data"]

    assert first_item["id"] != second_item["id"]

    assert first_item["participant_role"] == "seeker"
    assert first_item["inbox_side"] == "seeker"
    assert first_item["room_id"] == first_room.id
    assert first_item["relationship_id"] == first_room.id
    assert first_item["property_id"] == first_room.id

    assert second_item["participant_role"] == "seeker"
    assert second_item["inbox_side"] == "seeker"
    assert second_item["room_id"] == second_room.id
    assert second_item["relationship_id"] == second_room.id
    assert second_item["property_id"] == second_room.id

    client.force_authenticate(user=landlord)

    detail_response = client.get(
        f"/api/v1/messages/threads/{first_item['id']}/",
    )

    assert detail_response.status_code == 200

    detail_item = detail_response.data["data"]

    assert detail_item["participant_role"] == "landlord"
    assert detail_item["inbox_side"] == "landlord"
    assert detail_item["relationship_type"] == "room_enquiry"
    assert detail_item["relationship_id"] == first_room.id
    assert detail_item["property_id"] == first_room.id


def test_thread_list_openapi_declares_role_parameter():
    schema = SchemaGenerator().get_schema(
        request=None,
        public=True,
    )

    parameters = schema["paths"][
        "/api/v1/messages/threads/"
    ]["get"]["parameters"]

    role_parameter = next(
        parameter
        for parameter in parameters
        if parameter.get("name") == "role"
    )

    assert role_parameter["in"] == "query"
    assert role_parameter.get("required", False) is False
    assert set(role_parameter["schema"]["enum"]) == {
        "landlord",
        "seeker",
    }     


def test_thread_detail_is_scoped_to_authoritative_active_role():
    current_user = _mk_user("detail-role-user")
    landlord_counterpart = _mk_user("detail-landlord")
    seeker_counterpart = _mk_user("detail-seeker")
    legacy_counterpart = _mk_user("detail-legacy")

    profile, _ = UserProfile.objects.get_or_create(
        user=current_user
    )

    landlord_room = _mk_room(
        current_user,
        status="active",
        key_suffix="-l",
    )
    landlord_thread = MessageThread.objects.create(
        room=landlord_room,
        landlord=current_user,
        seeker=seeker_counterpart,
    )
    landlord_thread.participants.set(
        [current_user, seeker_counterpart]
    )

    seeker_room = _mk_room(
        landlord_counterpart,
        status="active",
        key_suffix="-s",
    )
    seeker_thread = MessageThread.objects.create(
        room=seeker_room,
        landlord=landlord_counterpart,
        seeker=current_user,
    )
    seeker_thread.participants.set(
        [landlord_counterpart, current_user]
    )

    legacy_thread = MessageThread.objects.create()
    legacy_thread.participants.set(
        [current_user, legacy_counterpart]
    )

    client = APIClient()
    client.force_authenticate(user=current_user)

    # Landlord mode: landlord + legacy allowed, seeker denied.
    profile.role = "landlord"
    profile.save(update_fields=["role"])

    landlord_response = client.get(
        f"/api/v1/messages/threads/{landlord_thread.id}/"
    )
    seeker_while_landlord_response = client.get(
        f"/api/v1/messages/threads/{seeker_thread.id}/"
    )
    legacy_while_landlord_response = client.get(
        f"/api/v1/messages/threads/{legacy_thread.id}/"
    )

    assert landlord_response.status_code == 200
    assert seeker_while_landlord_response.status_code == 404
    assert legacy_while_landlord_response.status_code == 200

    # Seeker mode: seeker + legacy allowed, landlord denied.
    profile.role = "seeker"
    profile.save(update_fields=["role"])

    seeker_response = client.get(
        f"/api/v1/messages/threads/{seeker_thread.id}/"
    )
    landlord_while_seeker_response = client.get(
        f"/api/v1/messages/threads/{landlord_thread.id}/"
    )
    legacy_while_seeker_response = client.get(
        f"/api/v1/messages/threads/{legacy_thread.id}/"
    )

    assert seeker_response.status_code == 200
    assert landlord_while_seeker_response.status_code == 404
    assert legacy_while_seeker_response.status_code == 200

    # Role switching must never delete the hidden threads.
    assert MessageThread.objects.filter(
        pk=landlord_thread.pk
    ).exists()
    assert MessageThread.objects.filter(
        pk=seeker_thread.pk
    ).exists()
    assert MessageThread.objects.filter(
        pk=legacy_thread.pk
    ).exists()