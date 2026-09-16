from datetime import timedelta

import pytest
from django.utils import timezone

from propertylist_app.models import Review, Tenancy
from propertylist_app.tasks import task_tenancy_prompts_sweep


def _make_tenancy(user_factory, room_factory, *, review_open_at, review_deadline_at):
    landlord = user_factory(
        username="deadline-landlord",
        email="deadline-landlord@example.com",
        role="landlord",
    )
    tenant = user_factory(
        username="deadline-tenant",
        email="deadline-tenant@example.com",
        role="seeker",
    )
    room = room_factory(property_owner=landlord)
    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=(review_open_at - timedelta(days=1)).date(),
        duration_months=1,
        status=Tenancy.STATUS_ENDED,
        review_open_at=review_open_at,
        review_deadline_at=review_deadline_at,
    )
    return tenancy, landlord, tenant


def _make_both_reviews(tenancy, landlord, tenant):
    tenant_review = Review.objects.create(
        tenancy=tenancy,
        reviewer=tenant,
        reviewee=landlord,
        role=Review.ROLE_TENANT_TO_LANDLORD,
        overall_rating=5,
        notes="Tenant review",
        active=False,
        reveal_at=tenancy.review_deadline_at,
    )
    landlord_review = Review.objects.create(
        tenancy=tenancy,
        reviewer=landlord,
        reviewee=tenant,
        role=Review.ROLE_LANDLORD_TO_TENANT,
        overall_rating=5,
        notes="Landlord review",
        active=False,
        reveal_at=tenancy.review_deadline_at,
    )
    return tenant_review, landlord_review


@pytest.mark.django_db
def test_both_reviews_stay_private_until_review_deadline(
    user_factory,
    room_factory,
):
    """Both submissions must not bypass the private review timer."""
    now = timezone.now()
    tenancy, landlord, tenant = _make_tenancy(
        user_factory,
        room_factory,
        review_open_at=now - timedelta(minutes=2),
        review_deadline_at=now + timedelta(minutes=8),
    )
    tenant_review, landlord_review = _make_both_reviews(
        tenancy,
        landlord,
        tenant,
    )

    task_tenancy_prompts_sweep()

    tenant_review.refresh_from_db()
    landlord_review.refresh_from_db()

    assert tenant_review.active is False
    assert landlord_review.active is False
    assert tenant_review.reveal_at == tenancy.review_deadline_at
    assert landlord_review.reveal_at == tenancy.review_deadline_at


@pytest.mark.django_db
def test_both_reviews_reveal_after_review_deadline(
    user_factory,
    room_factory,
):
    """The normal reveal sweep activates both reviews once the timer expires."""
    now = timezone.now()
    tenancy, landlord, tenant = _make_tenancy(
        user_factory,
        room_factory,
        review_open_at=now - timedelta(minutes=12),
        review_deadline_at=now - timedelta(minutes=2),
    )
    tenant_review, landlord_review = _make_both_reviews(
        tenancy,
        landlord,
        tenant,
    )

    task_tenancy_prompts_sweep()

    tenant_review.refresh_from_db()
    landlord_review.refresh_from_db()

    assert tenant_review.active is True
    assert landlord_review.active is True
