from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Room, RoomCategorie, Tenancy


@pytest.mark.django_db
def test_hidden_room_detail_is_visible_only_to_its_tenancy_participants(
    django_user_model,
):
    owner = django_user_model.objects.create_user(
        username="tenancy_room_owner",
        email="tenancy-room-owner@example.com",
        password="testpass123",
    )
    tenant = django_user_model.objects.create_user(
        username="tenancy_room_tenant",
        email="tenancy-room-tenant@example.com",
        password="testpass123",
    )
    stranger = django_user_model.objects.create_user(
        username="tenancy_room_stranger",
        email="tenancy-room-stranger@example.com",
        password="testpass123",
    )
    category = RoomCategorie.objects.create(
        name="Tenancy room access",
        active=True,
    )
    room = Room.objects.create(
        title="Rented hidden room",
        description="Room retained for the tenancy lifecycle.",
        location="SO14 0AA",
        price_per_month=800,
        security_deposit=800,
        property_owner=owner,
        category=category,
        status="hidden",
        is_available=False,
        paid_until=timezone.localdate() - timedelta(days=1),
    )
    Tenancy.objects.create(
        room=room,
        landlord=owner,
        tenant=tenant,
        proposed_by=tenant,
        move_in_date=timezone.localdate(),
        duration_months=6,
        landlord_confirmed_at=timezone.now(),
        tenant_confirmed_at=timezone.now(),
        status=Tenancy.STATUS_CONFIRMED,
    )

    url = reverse("v1:room-detail", kwargs={"pk": room.pk})
    client = APIClient()

    client.force_authenticate(user=tenant)
    tenant_response = client.get(url)
    assert tenant_response.status_code == 200
    assert tenant_response.data["data"]["id"] == room.id
    assert tenant_response.data["data"]["title"] == "Rented hidden room"

    client.force_authenticate(user=owner)
    assert client.get(url).status_code == 200

    client.force_authenticate(user=stranger)
    assert client.get(url).status_code == 404


@pytest.mark.django_db
def test_soft_deleted_tenancy_room_remains_private(django_user_model):
    owner = django_user_model.objects.create_user(
        username="deleted_tenancy_room_owner",
        email="deleted-tenancy-room-owner@example.com",
        password="testpass123",
    )
    tenant = django_user_model.objects.create_user(
        username="deleted_tenancy_room_tenant",
        email="deleted-tenancy-room-tenant@example.com",
        password="testpass123",
    )
    category = RoomCategorie.objects.create(
        name="Deleted tenancy room access",
        active=True,
    )
    room = Room.objects.create(
        title="Deleted rented room",
        description="A removed listing must not be exposed.",
        location="SO14 0AA",
        price_per_month=800,
        property_owner=owner,
        category=category,
        status="hidden",
        is_available=False,
        is_deleted=True,
    )
    Tenancy.objects.create(
        room=room,
        landlord=owner,
        tenant=tenant,
        proposed_by=tenant,
        move_in_date=timezone.localdate(),
        duration_months=6,
        status=Tenancy.STATUS_CONFIRMED,
    )

    client = APIClient()
    client.force_authenticate(user=tenant)
    response = client.get(reverse("v1:room-detail", kwargs={"pk": room.pk}))

    assert response.status_code == 404
