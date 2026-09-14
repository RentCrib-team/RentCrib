from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from propertylist_app.models import Tenancy

pytestmark = pytest.mark.django_db


def test_review_before_qa_window_does_not_report_stale_seven_day_rule(
    user_factory,
    room_factory,
):
    landlord = user_factory(username="qa_review_message_landlord")
    tenant = user_factory(username="qa_review_message_tenant")
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
        review_open_at=timezone.now() + timedelta(minutes=5),
        review_deadline_at=timezone.now() + timedelta(minutes=15),
    )

    client = APIClient()
    client.force_authenticate(user=tenant)

    response = client.post(
        f"/api/v1/tenancies/{tenancy.id}/reviews/create/",
        data={
            "overall_rating": 5,
            "notes": "Trying before the QA review window opens.",
        },
        format="json",
    )

    assert response.status_code == 400, response.data

    message = str(response.data)
    assert "7 days" not in message
    assert "seven days" not in message.lower()
    assert "Review window is not open yet" in message
