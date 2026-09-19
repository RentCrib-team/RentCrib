from datetime import date, timedelta

import pytest
from django.apps import apps
from django.utils import timezone

from propertylist_app.tasks import task_tenancy_prompts_sweep


pytestmark = pytest.mark.django_db


def test_review_phase_waits_until_ending_reminder_is_issued(
    user_factory,
    room_factory,
):
    Message = apps.get_model("propertylist_app", "Message")
    Notification = apps.get_model("propertylist_app", "Notification")
    Tenancy = apps.get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="review_guard_landlord")
    tenant = user_factory(username="review_guard_tenant")
    room = room_factory(property_owner=landlord)

    now = timezone.now()
    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=date.today() - timedelta(days=90),
        duration_months=12,
        status=Tenancy.STATUS_ACTIVE,
        landlord_confirmed_at=now - timedelta(days=90),
        tenant_confirmed_at=now - timedelta(days=90),
        # Recreate the legacy/backfill ordering bug: the review clock is
        # already due even though Timer 2 has not reached its reminder point.
        still_living_check_at=now + timedelta(minutes=5),
        review_open_at=now - timedelta(minutes=1),
        review_deadline_at=now + timedelta(minutes=9),
    )

    task_tenancy_prompts_sweep()

    tenancy.refresh_from_db()

    assert tenancy.status == Tenancy.STATUS_ACTIVE
    assert not Message.objects.filter(
        metadata__tenancy_id=tenancy.id,
        metadata__event_type="still_living_check",
        metadata__system_event=True,
    ).exists()
    assert not Notification.objects.filter(
        type="review_available",
        target_type="tenancy_review",
        target_id=tenancy.id,
    ).exists()
