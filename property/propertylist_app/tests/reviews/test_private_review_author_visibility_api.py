from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Review, Tenancy

pytestmark = pytest.mark.django_db


def _make_ended_reviewable_tenancy(*, landlord, tenant, room):
    return Tenancy.objects.create(
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


def test_api_submitted_private_review_is_immediately_visible_only_to_its_author(
    user_factory,
    room_factory,
):
    """The author sees their own private review while the counterparty stays blind."""
    landlord = user_factory(username="review_author_landlord")
    tenant = user_factory(username="review_author_tenant")
    room = room_factory(property_owner=landlord)
    tenancy = _make_ended_reviewable_tenancy(
        landlord=landlord,
        tenant=tenant,
        room=room,
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

    tenant_list_response = tenant_client.get("/api/v1/reviews/")
    assert tenant_list_response.status_code == 200, tenant_list_response.data
    tenant_list_payload = tenant_list_response.data.get(
        "data", tenant_list_response.data
    )
    assert any(item["id"] == review.id for item in tenant_list_payload)

    tenant_detail_response = tenant_client.get(
        f"/api/v1/reviews/{review.id}/"
    )
    assert tenant_detail_response.status_code == 200, tenant_detail_response.data
    assert tenant_detail_response.data["id"] == review.id

    landlord_client = APIClient()
    landlord_client.force_authenticate(user=landlord)

    landlord_response = landlord_client.get(
        f"/api/v1/tenancies/{tenancy.id}/reviews/"
    )
    assert landlord_response.status_code == 200, landlord_response.data
    assert landlord_response.data["other_review"] is None

    landlord_list_response = landlord_client.get("/api/v1/reviews/")
    assert landlord_list_response.status_code == 200, landlord_list_response.data
    landlord_list_payload = landlord_list_response.data.get(
        "data", landlord_list_response.data
    )
    assert all(item["id"] != review.id for item in landlord_list_payload)

    landlord_detail_response = landlord_client.get(
        f"/api/v1/reviews/{review.id}/"
    )
    assert landlord_detail_response.status_code in {403, 404}


def test_counterparty_stays_blind_before_reveal_even_if_active_flag_is_true(
    user_factory,
    room_factory,
):
    landlord = user_factory(username="review_guard_landlord")
    tenant = user_factory(username="review_guard_tenant")
    room = room_factory(property_owner=landlord)
    tenancy = _make_ended_reviewable_tenancy(
        landlord=landlord,
        tenant=tenant,
        room=room,
    )

    review = Review.objects.create(
        tenancy=tenancy,
        reviewer=tenant,
        reviewee=landlord,
        role=Review.ROLE_TENANT_TO_LANDLORD,
        overall_rating=5,
        notes="Should remain hidden until reveal time",
        reveal_at=timezone.now() + timedelta(minutes=10),
        active=True,
    )

    landlord_client = APIClient()
    landlord_client.force_authenticate(user=landlord)

    list_response = landlord_client.get("/api/v1/reviews/")
    assert list_response.status_code == 200, list_response.data
    list_payload = list_response.data.get("data", list_response.data)
    assert all(item["id"] != review.id for item in list_payload)

    detail_response = landlord_client.get(
        f"/api/v1/reviews/{review.id}/"
    )
    assert detail_response.status_code in {403, 404}

    tenancy_response = landlord_client.get(
        f"/api/v1/tenancies/{tenancy.id}/reviews/"
    )
    assert tenancy_response.status_code == 200, tenancy_response.data
    assert tenancy_response.data["other_review"] is None
