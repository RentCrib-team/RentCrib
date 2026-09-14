from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Review, Tenancy

pytestmark = pytest.mark.django_db


def test_api_submitted_private_review_is_immediately_visible_to_its_author(
    user_factory,
    room_factory,
):
    """The author sees their own private review while the counterparty stays blind."""
    landlord = user_factory(username="review_author_landlord")
    tenant = user_factory(username="review_author_tenant")
    room = room_factory(property_owner=landlord)

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
        review_deadline_at=timezone.now() + timedelta(minutes=10),
    )

    tenant_client = APIClient()
    tenant_client.force_authenticate(user=tenant)

    create_response = tenant_client.post(
        f"/api/v1/tenancies/{tenancy.id}/reviews/create/",
        data={"overall_rating": 5, "notes": "Private tenant review"},
        format="json",
    )
    assert create_response.status_code == 201, create_response.data

    review = Review.objects.get(
        tenancy=tenancy,
        role=Review.ROLE_TENANT_TO_LANDLORD,
    )
    assert review.active is False
    assert review.reveal_at == tenancy.review_deadline_at

    tenant_response = tenant_client.get(
        f"/api/v1/tenancies/{tenancy.id}/reviews/"
    )
    assert tenant_response.status_code == 200, tenant_response.data
    assert tenant_response.data["my_review"] is not None
    assert tenant_response.data["my_review"]["id"] == review.id
    assert tenant_response.data["other_review"] is None

    landlord_client = APIClient()
    landlord_client.force_authenticate(user=landlord)
    landlord_response = landlord_client.get(
        f"/api/v1/tenancies/{tenancy.id}/reviews/"
    )
    assert landlord_response.status_code == 200, landlord_response.data
    assert landlord_response.data["other_review"] is None
