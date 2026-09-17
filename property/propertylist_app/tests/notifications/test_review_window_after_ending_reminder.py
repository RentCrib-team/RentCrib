from datetime import date, timedelta

import pytest
from django.apps import apps
from django.utils import timezone

from propertylist_app.tasks import task_tenancy_prompts_sweep


pytestmark = pytest.mark.django_db


def test_review_window_repairs_from_original_ending_reminder(
    user_factory,
    room_factory,
):
    Message = apps.get_model("propertylist_app", "Message")
    MessageThread = apps.get_model(
        "propertylist_app",
        "MessageThread",
    )
    Notification = apps.get_model("propertylist_app", "Notification")
    Tenancy = apps.get_model("propertylist_app", "Tenancy")

    landlord = user_factory(username="ending_reminder_landlord")
    tenant = user_factory(username="ending_reminder_tenant")
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
        still_living_check_at=now - timedelta(minutes=1),
        review_open_at=now + timedelta(days=365),
        review_deadline_at=now + timedelta(days=395),
    )

    thread = MessageThread.objects.create()
    thread.participants.set([landlord, tenant])
    Message.objects.create(
        thread=thread,
        sender=landlord,
        body="Tenancy confirmed",
        metadata={"tenancy_id": tenancy.id},
    )

    task_tenancy_prompts_sweep()

    ending_message = Message.objects.get(
        metadata__tenancy_id=tenancy.id,
        metadata__event_type="still_living_check",
        metadata__system_event=True,
    )
    assert ending_message.metadata["available_actions"] == [
        "update_tenancy"
    ]

    reminder_dropped_at = now - timedelta(minutes=11)
    Message.objects.filter(id=ending_message.id).update(
        created=reminder_dropped_at,
    )

    # Recreate the bug: another lifecycle save restored the real tenancy-end
    # dates after the ending reminder had already been posted.
    Tenancy.objects.filter(id=tenancy.id).update(
        review_open_at=now + timedelta(days=365),
        review_deadline_at=now + timedelta(days=395),
        still_living_landlord_confirmed_at=None,
        still_living_tenant_confirmed_at=None,
        still_living_confirmed_at=None,
    )

    recovery_started_at = timezone.now()
    task_tenancy_prompts_sweep()
    recovery_finished_at = timezone.now()

    tenancy.refresh_from_db()
    ending_message.refresh_from_db()

    # The reminder is already overdue. The review notification must open
    # a fresh window now, rather than create a deadline in the past.
    assert (
        recovery_started_at
        <= tenancy.review_open_at
        <= recovery_finished_at
    )
    assert tenancy.review_deadline_at == (
        tenancy.review_open_at + timedelta(minutes=10)
    )
    assert tenancy.review_deadline_at > recovery_finished_at
    assert tenancy.status == Tenancy.STATUS_ENDED
    assert ending_message.metadata["available_actions"] == []

    review_notifications = Notification.objects.filter(
        type="review_available",
        target_type="tenancy_review",
        target_id=tenancy.id,
    )
    assert set(
        review_notifications.values_list("user_id", flat=True)
    ) == {landlord.id, tenant.id}
