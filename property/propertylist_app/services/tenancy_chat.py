from __future__ import annotations

from typing import Tuple

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from propertylist_app.models import Message, MessageThread, Tenancy


EVENT_MESSAGE_TYPES = {
    "proposed": Message.TYPE_TENANCY_PROPOSAL,
    "updated": Message.TYPE_TENANCY_UPDATED,
    "confirmed": Message.TYPE_TENANCY_CONFIRMED,
    "cancelled": Message.TYPE_TENANCY_CANCELLED,
}


EVENT_BODIES = {
    "proposed": "A tenancy proposal has been created.",
    "updated": "The tenancy proposal has been updated.",
    "confirmed": "The tenancy has been confirmed.",
    "cancelled": "The tenancy proposal has been cancelled.",
}


@transaction.atomic
def post_tenancy_event(
    tenancy: Tenancy,
    event_type: str,
    sender,
) -> Tuple[MessageThread, Message]:
    """
    Reuse or create the room conversation and add one structured
    tenancy event message.

    The operation is idempotent: retrying the same event does not
    create a duplicate chat message.
    """

    if event_type not in EVENT_MESSAGE_TYPES:
        raise ValidationError(
            f"Unsupported tenancy chat event: {event_type}"
        )

    if not tenancy or not tenancy.pk:
        raise ValidationError("A saved tenancy is required.")

    if sender is None or not getattr(sender, "pk", None):
        raise ValidationError("A valid message sender is required.")

    # Lock the tenancy while processing so simultaneous Celery retries
    # cannot create the same event message twice.
    tenancy = (
        Tenancy.objects
        .select_for_update()
        .select_related("room", "landlord", "tenant")
        .get(pk=tenancy.pk)
    )

    if sender.pk not in {tenancy.landlord_id, tenancy.tenant_id}:
        raise ValidationError(
            "The tenancy message sender must be the landlord or tenant."
        )

    message_type = EVENT_MESSAGE_TYPES[event_type]
    body = EVENT_BODIES[event_type]

    # A proposal uses its creation time. Later events use the time at
    # which the tenancy was last changed.
    event_time = (
        tenancy.created_at
        if event_type == "proposed"
        else tenancy.updated_at
    )

    event_key = (
        f"tenancy:{tenancy.pk}:"
        f"{event_type}:{event_time.isoformat()}"
    )

    # Celery may retry a task. Return the message already created for
    # this exact event instead of creating a duplicate.
    existing_message = (
        Message.objects
        .select_related("thread")
        .filter(
            message_type=message_type,
            metadata__event_key=event_key,
        )
        .first()
    )

    if existing_message:
        return existing_message.thread, existing_message

    room = tenancy.room
    landlord = tenancy.landlord
    tenant = tenancy.tenant

    # Reuse the same room-based thread logic already used by
    # StartThreadFromRoomView.
    thread = (
        MessageThread.objects
        .filter(Q(room=room) | Q(room__isnull=True))
        .filter(participants=landlord)
        .filter(participants=tenant)
        .distinct()
        .first()
    )

    if thread is None:
        thread = MessageThread.objects.create(room=room)
        thread.participants.set([landlord, tenant])

    elif thread.room_id is None:
        thread.room = room
        thread.save(update_fields=["room"])

    message = Message.objects.create(
        thread=thread,
        sender=sender,
        body=body,
        message_type=message_type,
        metadata={
            "tenancy_id": tenancy.pk,
            "event_type": event_type,
            "event_key": event_key,
        },
    )

    return thread, message