from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie, Tenancy


pytestmark = pytest.mark.django_db

API_PREFIX = "/api/v1"


def _make_user(username: str):
    User = get_user_model()

    return User.objects.create_user(
        username=username,
        password="pass12345",
        email=f"{username}@example.com",
    )


def _make_room(owner):
    category = RoomCategorie.objects.create(name="Standard")

    return Room.objects.create(
        title="Tenancy detail test room",
        description="Clean room",
        price_per_month="500.00",
        location="Southampton",
        category=category,
        furnished=False,
        bills_included=False,
        property_owner=owner,
        property_type="flat",
    )


def _make_tenancy(*, landlord, tenant, room):
    return Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() + timedelta(days=7),
        duration_months=6,
        status=Tenancy.STATUS_PROPOSED,
    )


def _authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_landlord_can_retrieve_own_tenancy():
    landlord = _make_user("detail_landlord")
    tenant = _make_user("detail_tenant")
    room = _make_room(landlord)
    tenancy = _make_tenancy(
        landlord=landlord,
        tenant=tenant,
        room=room,
    )

    client = _authenticated_client(landlord)

    response = client.get(
        f"{API_PREFIX}/tenancies/{tenancy.id}/",
    )

    assert response.status_code == 200, response.data
    assert response.data["ok"] is True
    assert response.data["data"]["id"] == tenancy.id
    assert response.data["data"]["landlord"] == landlord.id
    assert response.data["data"]["tenant"] == tenant.id

    # The original proposer must wait for the other party.
    assert response.data["data"]["can_agree"] is False
    assert response.data["data"]["can_edit"] is False
    assert response.data["data"]["available_actions"] == []


def test_tenant_can_retrieve_own_tenancy_with_review_actions():
    landlord = _make_user("detail_landlord_two")
    tenant = _make_user("detail_tenant_two")
    room = _make_room(landlord)
    tenancy = _make_tenancy(
        landlord=landlord,
        tenant=tenant,
        room=room,
    )

    client = _authenticated_client(tenant)

    response = client.get(
        f"{API_PREFIX}/tenancies/{tenancy.id}/",
    )

    assert response.status_code == 200, response.data
    assert response.data["data"]["id"] == tenancy.id
    assert response.data["data"]["can_agree"] is True
    assert response.data["data"]["can_edit"] is True
    assert response.data["data"]["available_actions"] == [
        "confirm",
        "propose_changes",
    ]


def test_unrelated_user_receives_not_found():
    landlord = _make_user("detail_landlord_three")
    tenant = _make_user("detail_tenant_three")
    unrelated_user = _make_user("detail_outsider")
    room = _make_room(landlord)
    tenancy = _make_tenancy(
        landlord=landlord,
        tenant=tenant,
        room=room,
    )

    client = _authenticated_client(unrelated_user)

    response = client.get(
        f"{API_PREFIX}/tenancies/{tenancy.id}/",
    )

    assert response.status_code == 404, response.data


def test_missing_tenancy_returns_not_found():
    user = _make_user("detail_missing_user")
    client = _authenticated_client(user)

    response = client.get(
        f"{API_PREFIX}/tenancies/999999/",
    )

    assert response.status_code == 404, response.data


def test_authentication_is_required():
    client = APIClient()

    response = client.get(
        f"{API_PREFIX}/tenancies/999999/",
    )

    assert response.status_code == 401, response.data