import pytest
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie, Tenancy
from propertylist_app.tasks import expire_paid_listings


@pytest.mark.django_db
def test_hidden_room_not_in_list_or_search():
    cat = RoomCategorie.objects.create(name="Standard", active=True)

    User = get_user_model()
    owner = User.objects.create_user(username="visibility_owner", password="pass12345")
    paid_until = timezone.now().date() + timedelta(days=30)

    Room.objects.create(
    title="Public Room",
    category=cat,
    property_owner=owner,
    price_per_month=600,
    status="active",
    paid_until=paid_until,
    )
    Room.objects.create(
        title="Hidden Room",
        category=cat,
        property_owner=owner,
        price_per_month=700,
        status="hidden",
    )
    Room.objects.create(
        title="Expired Room",
        category=cat,
        property_owner=owner,
        price_per_month=800,
        status="active",
        paid_until=timezone.now().date() - timedelta(days=1),
    )

    client = APIClient()

    r_list = client.get("/api/v1/rooms/")
    assert r_list.status_code == 200
    payload = r_list.json()
    titles = [r["title"] for r in payload["results"]]

    assert "Public Room" in titles
    assert "Hidden Room" not in titles
    assert "Expired Room" not in titles

    r_search = client.get("/api/v1/search/rooms/?q=Room")
    assert r_search.status_code == 200
    data = r_search.json()
    items = data if isinstance(data, list) else data.get("results", data)
    titles = [i["title"] for i in items]

    assert "Public Room" in titles
    assert "Hidden Room" not in titles
    assert "Expired Room" not in titles


@pytest.mark.django_db
def test_expired_room_keeps_active_lifecycle_after_scheduler():
    cat = RoomCategorie.objects.create(name="Premium", active=True)

    User = get_user_model()
    owner = User.objects.create_user(username="expired_visibility_owner", password="pass12345")

    room = Room.objects.create(
        title="Old Listing",
        category=cat,
        property_owner=owner,
        price_per_month=950,
        status="active",
        paid_until=timezone.now().date() - timedelta(days=1),
    )

    expire_paid_listings()

    room.refresh_from_db()
    assert room.status == "active"


@pytest.mark.django_db
def test_paid_active_but_unavailable_room_not_in_public_search():
    cat = RoomCategorie.objects.create(
        name="Unavailable Search Test",
        active=True,
    )

    User = get_user_model()

    owner = User.objects.create_user(
        username="unavailable_search_owner",
        password="pass12345",
    )

    room = Room.objects.create(
        title="Already Rented Paid Room",
        category=cat,
        property_owner=owner,
        price_per_month=900,
        location="London",
        status="active",
        is_available=False,
        paid_until=timezone.now().date() + timedelta(days=30),
    )

    client = APIClient()

    response = client.get(
        "/api/v1/search/rooms/",
        {"q": "Already Rented Paid Room"},
    )

    assert response.status_code == 200

    data = response.json()

    if isinstance(data, dict) and "data" in data:
        data = data["data"]

    results = data.get("results", data) if isinstance(data, dict) else data

    ids = {item["id"] for item in results}

    assert room.id not in ids


@pytest.mark.django_db
def test_tenancy_participant_can_retrieve_hidden_rented_room():
    User = get_user_model()
    landlord = User.objects.create_user(
        username="tenancy_detail_landlord",
        password="pass12345",
    )
    tenant = User.objects.create_user(
        username="tenancy_detail_tenant",
        password="pass12345",
    )
    stranger = User.objects.create_user(
        username="tenancy_detail_stranger",
        password="pass12345",
    )
    category = RoomCategorie.objects.create(
        name="Tenancy detail room",
        active=True,
    )
    room = Room.objects.create(
        title="Golden Gate Residence",
        category=category,
        property_owner=landlord,
        price_per_month=900,
        status="hidden",
        is_available=False,
    )
    Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        move_in_date=timezone.now().date(),
        duration_months=6,
        status=Tenancy.STATUS_ACTIVE,
    )

    participant_client = APIClient()
    participant_client.force_authenticate(user=tenant)
    participant_response = participant_client.get(
        f"/api/v1/rooms/{room.id}/",
    )

    assert participant_response.status_code == 200
    assert participant_response.json()["data"]["title"] == "Golden Gate Residence"

    stranger_client = APIClient()
    stranger_client.force_authenticate(user=stranger)
    stranger_response = stranger_client.get(
        f"/api/v1/rooms/{room.id}/",
    )

    assert stranger_response.status_code == 404
