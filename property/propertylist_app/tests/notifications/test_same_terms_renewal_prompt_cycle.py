from datetime import date, timedelta

import pytest
from django.utils import timezone

from propertylist_app.models import (
    Message,
    MessageThread,
    Notification,
    Tenancy,
    TenancyExtension,
)
from propertylist_app.tasks import task_tenancy_prompts_sweep


pytestmark = pytest.mark.django_db


def test_same_terms_renewal_gets_fresh_ending_reminder_message(
    user_factory,
    room_factory,
):
    landlord = user_factory(
        username="same_terms_renewal_landlord",
        role="landlord",
    )
    tenant = user_factory(
        username="same_terms_renewal_tenant",
        role="seeker",
    )
    room = room_factory(property_owner=landlord)

    now = timezone.now()
    move_in_date = date.today() - timedelta(days=90)

    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=move_in_date,
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

    legacy_event_key = (
        f"tenancy:{tenancy.id}:"
        f"{move_in_date.isoformat()}:"
        "12:"
        "still_living_check"
    )

    previous_cycle_prompt = Message.objects.create(
        thread=thread,
        sender=landlord,
        body="Previous cycle ending reminder",
        message_type=Message.TYPE_TEXT,
        metadata={
            "tenancy_id": tenancy.id,
            "room_id": room.id,
            "room_title": room.title,
            "event_type": "still_living_check",
            "event_key": legacy_event_key,
            "system_event": True,
            "available_actions": ["update_tenancy"],
        },
    )
    Message.objects.filter(pk=previous_cycle_prompt.pk).update(
        created=now - timedelta(minutes=30),
    )
    previous_cycle_prompt.refresh_from_db()

    renewal_accepted_at = now - timedelta(minutes=11)
    extension = TenancyExtension.objects.create(
        tenancy=tenancy,
        proposed_by=tenant,
        proposed_start_date=move_in_date,
        proposed_duration_months=12,
        status=TenancyExtension.STATUS_ACCEPTED,
        responded_at=renewal_accepted_at,
    )

    task_tenancy_prompts_sweep()

    tenancy.refresh_from_db()

    prompts = list(
        Message.objects.filter(
            metadata__tenancy_id=tenancy.id,
            metadata__event_type="still_living_check",
            metadata__system_event=True,
        ).order_by("created", "id")
    )

    assert len(prompts) == 2
    fresh_prompt = prompts[-1]

    assert fresh_prompt.id != previous_cycle_prompt.id
    assert fresh_prompt.created >= renewal_accepted_at
    assert fresh_prompt.metadata["event_key"] == (
        f"{legacy_event_key}:renewal:{extension.id}"
    )

    expected_review_open_at = (
        fresh_prompt.created + timedelta(minutes=10)
    )
    assert tenancy.review_open_at == expected_review_open_at
    assert tenancy.review_open_at > now
    assert tenancy.status == Tenancy.STATUS_ACTIVE
    assert not Notification.objects.filter(
        type="review_available",
        target_type="tenancy_review",
        target_id=tenancy.id,
    ).exists()

    # A retry in the same renewal cycle must reuse the fresh message rather
    # than creating another reminder or changing the review anchor.
    task_tenancy_prompts_sweep()

    tenancy.refresh_from_db()
    assert Message.objects.filter(
        metadata__tenancy_id=tenancy.id,
        metadata__event_type="still_living_check",
        metadata__system_event=True,
    ).count() == 2
    assert tenancy.review_open_at == expected_review_open_at
