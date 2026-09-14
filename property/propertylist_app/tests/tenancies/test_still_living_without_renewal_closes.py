from datetime import date, timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Tenancy
from propertylist_app.tasks import task_tenancy_prompts_sweep

pytestmark = pytest.mark.django_db


def test_both_still_living_confirmations_do_not_keep_old_tenancy_alive_after_window(
    user_factory,
    room_factory,
):
    landlord = user_factory(username="still_close_landlord")
    tenant = user_factory(username="still_close_tenant")
    room = room_factory(property_owner=landlord)

    room.is_available = False
    room.save(update_fields=["is_available", "updated_at"])

    now = timezone.now()
    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() - timedelta(days=90),
        duration_months=3,
        status=Tenancy.STATUS_ACTIVE,
        landlord_confirmed_at=now - timedelta(days=90),
        tenant_confirmed_at=now - timedelta(days=90),
        still_living_check_at=now - timedelta(minutes=20),
        review_open_at=now + timedelta(minutes=10),
        review_deadline_at=now + timedelta(minutes=20),
    )

    landlord_client = APIClient()
    landlord_client.force_authenticate(user=landlord)
    tenant_client = APIClient()
    tenant_client.force_authenticate(user=tenant)

    landlord_response = landlord_client.patch(
        f"/api/v1/tenancies/{tenancy.id}/still-living/confirm/",
        data={},
        format="json",
    )
    assert landlord_response.status_code == 200, landlord_response.data

    tenant_response = tenant_client.patch(
        f"/api/v1/tenancies/{tenancy.id}/still-living/confirm/",
        data={},
        format="json",
    )
    assert tenant_response.status_code == 200, tenant_response.data

    tenancy.refresh_from_db()
    assert tenancy.still_living_confirmed_at is not None

    # No renewal was proposed/accepted. Once the existing update window has
    # closed, the old tenancy must still end instead of remaining active
    # forever merely because both parties answered the checkpoint.
    tenancy.review_open_at = timezone.now() - timedelta(seconds=1)
    tenancy.review_deadline_at = timezone.now() + timedelta(minutes=10)
    tenancy.save(update_fields=["review_open_at", "review_deadline_at"])

    task_tenancy_prompts_sweep()

    tenancy.refresh_from_db()
    room.refresh_from_db()

    assert tenancy.status == Tenancy.STATUS_ENDED
    assert room.is_available is True
