from datetime import date, timedelta

import pytest
from django.apps import apps
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient


pytestmark = pytest.mark.django_db


def test_confirmed_future_move_in_tenancy_can_confirm_when_timer_2_is_due(
    user_factory,
    room_factory,
):
    Tenancy = apps.get_model("propertylist_app", "Tenancy")
    now = timezone.now()

    landlord = user_factory(username="sl_confirmed_landlord")
    tenant = user_factory(username="sl_confirmed_tenant")
    room = room_factory(property_owner=landlord)

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() + timedelta(days=30),
        duration_months=3,
        status=Tenancy.STATUS_CONFIRMED,
        landlord_confirmed_at=now - timedelta(minutes=20),
        tenant_confirmed_at=now - timedelta(minutes=20),
        still_living_check_at=now - timedelta(minutes=1),
    )

    client = APIClient()
    client.force_authenticate(user=tenant)

    response = client.patch(
        reverse(
            "v1:tenancy-still-living-confirm",
            kwargs={"tenancy_id": tenancy.id},
        ),
        data={},
        format="json",
    )

    assert response.status_code in (200, 204)

    tenancy.refresh_from_db()
    assert tenancy.status == Tenancy.STATUS_CONFIRMED
    assert tenancy.still_living_tenant_confirmed_at is not None
