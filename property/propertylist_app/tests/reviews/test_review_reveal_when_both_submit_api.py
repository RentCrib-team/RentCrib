from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Review, Tenancy
from propertylist_app.tasks import task_tenancy_prompts_sweep

pytestmark = pytest.mark.django_db


def test_both_api_reviews_wait_for_scheduled_reveal_after_both_submit(
    user_factory,
    room_factory,
):
    landlord = user_factory(username="both_review_landlord")
    tenant = user_factory(username="both_review_tenant")
    room = room_factory(property_owner=landlord)

    scheduled_reveal = timezone.now() + timedelta(minutes=10)

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=timezone.localdate() - timedelta(days=30),
        duration_months=1,
        status=Tenancy.STATUS_ENDED,
        landlord_confirmed_at=timezone.now() - timedelta(days=30),
        tenant_confirmed_at=timezone.now() - timedelta(days=30),
        review_open_at=timezone.now() - timedelta(seconds=1),
        review_deadline_at=scheduled_reveal,
    )

    tenant_client = APIClient()
    tenant_client.force_authenticate(user=tenant)
    tenant_response = tenant_client.post(
        f"/api/v1/tenancies/{tenancy.id}/reviews/create/",
        data={"overall_rating": 5, "notes": "Tenant review"},
        format="json",
    )
    assert tenant_response.status_code == 201, tenant_response.data

    landlord_client = APIClient()
    landlord_client.force_authenticate(user=landlord)
    landlord_response = landlord_client.post(
        f"/api/v1/tenancies/{tenancy.id}/reviews/create/",
        data={"overall_rating": 4, "notes": "Landlord review"},
        format="json",
    )
    assert landlord_response.status_code == 201, landlord_response.data

    reviews = Review.objects.filter(tenancy=tenancy)
    assert reviews.count() == 2
    assert reviews.filter(active=False).count() == 2

    # Both reviews arriving early must not defeat the scheduled reveal.
    # The first sweep occurs before the established reveal time, so both
    # reviews must remain private/double-blind.
    task_tenancy_prompts_sweep()

    reviews = Review.objects.filter(tenancy=tenancy)
    assert reviews.filter(active=False).count() == 2
    assert reviews.filter(active=True).count() == 0

    # Simulate the already-established scheduled reveal becoming due.
    Review.objects.filter(tenancy=tenancy).update(
        reveal_at=timezone.now() - timedelta(seconds=1)
    )

    task_tenancy_prompts_sweep()

    assert Review.objects.filter(tenancy=tenancy, active=True).count() == 2
