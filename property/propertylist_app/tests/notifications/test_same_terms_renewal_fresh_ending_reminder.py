from datetime import date, timedelta

import pytest
from django.apps import apps
from django.utils import timezone

from propertylist_app.tasks import task_tenancy_prompts_sweep


pytestmark = pytest.mark.django_db


def test_same_terms_renewal_gets_fresh_ending_reminder_cycle(
    user_factory,
    room_factory,
):
    Message = apps.get_model("propertylist_app", "Message")
    MessageThread = apps.get_model(
        "propertylist_app",
        "MessageThread",
    )
    Tenancy = apps.get_model("propertylist_app", "Tenancy")
    TenancyExtension = apps.get_model(
        "propertylist_app",
        "TenancyExtension",
    )

    landlord = user_factory(username="bug9_landlord")
    tenant = user_factory(username="bug9_tenant")
    room = room_factory(property_owner=landlord)

    now = timezone.now()
    move_in_date = date.today() - timedelta(days=90)
    duration_months = 12

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=move_in_date,
        duration_months=duration_months,
        status=Tenancy.STATUS_ACTIVE,
        landlord_confirmed_at=now - timedelta(days=90),
        tenant_confirmed_at=now - timedelta(days=90),
        still_living_check_at=now - timedelta(minutes=1),
        review_open_at=now + timedelta(minutes=9),
        review_deadline_at=now + timedelta(minutes=19),
    )

    thread = MessageThread.objects.create()
    thread.participants.set([landlord, tenant])

    Message.objects.create(
        thread=thread,
        sender=landlord,
        body="Tenancy confirmed",
        metadata={"tenancy_id": tenancy.id},
    )

    old_event_key = (
        f"tenancy:{tenancy.id}:"
        f"{move_in_date.isoformat()}:"
        f"{duration_months}:"
        "still_living_check"
    )

    old_reminder = Message.objects.create(
        thread=thread,
        sender=landlord,
        body="Old ending reminder",
        message_type=Message.TYPE_TEXT,
        metadata={
            "tenancy_id": tenancy.id,
            "room_id": room.id,
            "room_title": room.title,
            "event_type": "still_living_check",
            "event_key": old_event_key,
            "system_event": True,
            "available_actions": ["update_tenancy"],
        },
    )

    old_created_at = now - timedelta(minutes=30)
    Message.objects.filter(pk=old_reminder.pk).update(
        created=old_created_at,
    )

    accepted_extension = TenancyExtension.objects.create(
        tenancy=tenancy,
        proposed_by=landlord,
        proposed_start_date=move_in_date,
        proposed_duration_months=duration_months,
        status=TenancyExtension.STATUS_ACCEPTED,
        responded_at=now - timedelta(minutes=5),
    )

    sweep_started_at = timezone.now()
    task_tenancy_prompts_sweep()
    sweep_finished_at = timezone.now()

    tenancy.refresh_from_db()

    reminders = Message.objects.filter(
        metadata__tenancy_id=tenancy.id,
        metadata__event_type="still_living_check",
        metadata__system_event=True,
    ).order_by("created", "id")

    assert reminders.count() == 2

    fresh_reminder = reminders.last()

    assert fresh_reminder.id != old_reminder.id
    assert fresh_reminder.created >= sweep_started_at
    assert fresh_reminder.created <= sweep_finished_at
    assert (
        fresh_reminder.metadata["event_key"]
        == (
            f"tenancy:{tenancy.id}:"
            f"{move_in_date.isoformat()}:"
            f"{duration_months}:"
            f"renewal-{accepted_extension.id}:"
            "still_living_check"
        )
    )

    assert tenancy.review_open_at == (
        fresh_reminder.created + timedelta(minutes=10)
    )
    assert tenancy.review_open_at > sweep_finished_at
