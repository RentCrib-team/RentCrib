import pytest

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie, RoomImage


@pytest.fixture
def landlord(django_user_model):
    return django_user_model.objects.create_user(
        username="photo_visibility_landlord",
        email="photo_visibility_landlord@example.com",
        password="testpass123",
    )


@pytest.fixture
def other_user(django_user_model):
    return django_user_model.objects.create_user(
        username="photo_visibility_other",
        email="photo_visibility_other@example.com",
        password="testpass123",
    )


@pytest.fixture
def room(landlord):
    category = RoomCategorie.objects.create(
        name="Photo visibility category",
        active=True,
    )

    return Room.objects.create(
        title="Photo visibility test room",
        description="A spacious room used for testing photo visibility behaviour.",
        location="SO14 0AA",
        price_per_month=700,
        security_deposit=700,
        property_owner=landlord,
        category=category,
    )


@pytest.fixture
def room_photos(room):
    approved = RoomImage.objects.create(
        room=room,
        image="room_images/approved.jpg",
        status="approved",
    )

    pending = RoomImage.objects.create(
        room=room,
        image="room_images/pending.jpg",
        status="pending",
    )

    rejected = RoomImage.objects.create(
        room=room,
        image="room_images/rejected.jpg",
        status="rejected",
    )

    return {
        "approved": approved,
        "pending": pending,
        "rejected": rejected,
    }


def photo_statuses(response):
    assert response.data["ok"] is True
    return [photo["status"] for photo in response.data["data"]]


@pytest.mark.django_db
def test_room_owner_can_see_all_photo_statuses(
    landlord,
    room,
    room_photos,
):
    client = APIClient()
    client.force_authenticate(user=landlord)

    response = client.get(
        reverse("api:room-photo-upload", args=[room.id])
    )

    assert response.status_code == status.HTTP_200_OK

    assert photo_statuses(response) == [
        "approved",
        "pending",
        "rejected",
    ]

    assert [
        photo["id"] for photo in response.data["data"]
    ] == [
        room_photos["approved"].id,
        room_photos["pending"].id,
        room_photos["rejected"].id,
    ]


@pytest.mark.django_db
def test_public_only_sees_approved_photo(
    room,
    room_photos,
):
    client = APIClient()

    response = client.get(
        reverse("api:room-photo-upload", args=[room.id])
    )

    assert response.status_code == status.HTTP_200_OK
    assert photo_statuses(response) == ["approved"]
    assert response.data["data"][0]["id"] == room_photos["approved"].id


@pytest.mark.django_db
def test_other_authenticated_user_only_sees_approved_photo(
    other_user,
    room,
    room_photos,
):
    client = APIClient()
    client.force_authenticate(user=other_user)

    response = client.get(
        reverse("api:room-photo-upload", args=[room.id])
    )

    assert response.status_code == status.HTTP_200_OK
    assert photo_statuses(response) == ["approved"]
    assert response.data["data"][0]["id"] == room_photos["approved"].id