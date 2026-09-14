from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from propertylist_app.api.serializers import MessageSerializer
from propertylist_app.models import Booking, Message, Tenancy
from propertylist_app.services.message_threads import get_or_create_canonical_thread

pytestmark = pytest.mark.django_db


def test_new_completed_viewing_can_start_new_cycle_after_old_tenancy_ended(
    user_factory,
    room_factory,
):
    landlord = user_factory(username="reused_room_landlord")
    tenant = user_factory(username="reused_room_tenant")
    room = room_factory(property_owner=landlord)

    # Historical tenancy for this exact landlord/tenant/room relationship.
    Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=timezone.localdate() - timedelta(days=60),
        duration_months=1,
        status=Tenancy.STATUS_ENDED,
        landlord_confirmed_at=timezone.now() - timedelta(days=60),
        tenant_confirmed_at=timezone.now() - timedelta(days=60),
    )

    # The same seeker legitimately views the relisted room again later.
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
    message = Message.objects.create(
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

    def actions_for(user):
        request = SimpleNamespace(user=user)
        return MessageSerializer(
            message,
            context={"request": request},
        ).data["available_actions"]

    # An ended historical tenancy must not poison a new rental cycle.
    assert actions_for(landlord) == ["update_tenancy"]
    assert actions_for(tenant) == ["update_tenancy"]


def test_new_completed_viewing_stays_blocked_while_live_tenancy_exists(
    user_factory,
    room_factory,
):
    landlord = user_factory(username="live_room_landlord")
    tenant = user_factory(username="live_room_tenant")
    room = room_factory(property_owner=landlord)

    Tenancy.objects.create(
        room=room,
        landlord=landlord,
        tenant=tenant,
        proposed_by=landlord,
        move_in_date=timezone.localdate() + timedelta(days=7),
        duration_months=6,
        status=Tenancy.STATUS_PROPOSED,
    )

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
    message = Message.objects.create(
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

    request = SimpleNamespace(user=tenant)
    actions = MessageSerializer(
        message,
        context={"request": request},
    ).data["available_actions"]

    assert actions == []
