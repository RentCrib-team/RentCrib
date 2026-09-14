from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from propertylist_app.api.serializers import MessageSerializer
from propertylist_app.models import Booking, Message, Tenancy
from propertylist_app.services.message_threads import get_or_create_canonical_thread

pytestmark = pytest.mark.django_db


def _completed_viewing_message(*, landlord, tenant, room):
    now = timezone.now()
    booking = Booking.objects.create(
        user=tenant,
        room=room,
        start=now - timedelta(minutes=31),
        end=now - timedelta(minutes=1),
        status=Booking.STATUS_ACTIVE,
        is_deleted=False,
        canceled_at=None,
    )

    thread = get_or_create_canonical_thread(
        landlord=landlord,
        seeker=tenant,
        room=room,
    )

    return Message.objects.create(
        thread=thread,
        sender=landlord,
        body="Viewing completed",
        message_type=Message.TYPE_TEXT,
        metadata={
            "system_event": True,
            "event_type": "booking_completed",
            "booking_id": booking.id,
            "room_id": room.id,
        },
    )


def _actions_for(message, user):
    request = SimpleNamespace(user=user)
    return MessageSerializer(
        message,
        context={"request": request},
    ).data["available_actions"]


@pytest.mark.parametrize(
    "terminal_status",
    [
        Tenancy.STATUS_ENDED,
        Tenancy.STATUS_CANCELLED,
    ],
)
def test_new_completed_viewing_can_start_new_cycle_after_terminal_tenancy(
    user_factory,
    room_factory,
    terminal_status,
):
    landlord = user_factory(username=f"reused_room_landlord_{terminal_status}")
    tenant = user_factory(username=f"reused_room_tenant_{terminal_status}")
    room = room_factory(property_owner=landlord)

    historical = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=timezone.localdate() - timedelta(days=60),
        duration_months=1,
        status=terminal_status,
    )

    if terminal_status == Tenancy.STATUS_ENDED:
        historical.landlord_confirmed_at = timezone.now() - timedelta(days=60)
        historical.tenant_confirmed_at = timezone.now() - timedelta(days=60)
        historical.save(
            update_fields=[
                "landlord_confirmed_at",
                "tenant_confirmed_at",
            ]
        )

    message = _completed_viewing_message(
        landlord=landlord,
        tenant=tenant,
        room=room,
    )

    # Terminal history belongs to an old lifecycle. It must not suppress the
    # action for a later legitimate viewing of the same relisted room.
    assert _actions_for(message, landlord) == ["update_tenancy"]
    assert _actions_for(message, tenant) == ["update_tenancy"]


@pytest.mark.parametrize(
    "live_status",
    [
        Tenancy.STATUS_PROPOSED,
        Tenancy.STATUS_CONFIRMED,
        Tenancy.STATUS_ACTIVE,
    ],
)
def test_new_completed_viewing_stays_blocked_while_live_tenancy_exists(
    user_factory,
    room_factory,
    live_status,
):
    landlord = user_factory(username=f"live_room_landlord_{live_status}")
    tenant = user_factory(username=f"live_room_tenant_{live_status}")
    room = room_factory(property_owner=landlord)

    now = timezone.now()
    tenancy = Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=timezone.localdate() + timedelta(days=7),
        duration_months=6,
        status=live_status,
    )

    if live_status in {
        Tenancy.STATUS_CONFIRMED,
        Tenancy.STATUS_ACTIVE,
    }:
        tenancy.landlord_confirmed_at = now
        tenancy.tenant_confirmed_at = now
        tenancy.save(
            update_fields=[
                "landlord_confirmed_at",
                "tenant_confirmed_at",
            ]
        )

    message = _completed_viewing_message(
        landlord=landlord,
        tenant=tenant,
        room=room,
    )

    assert _actions_for(message, landlord) == []
    assert _actions_for(message, tenant) == []
