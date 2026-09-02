from django.db import IntegrityError, transaction
from django.db.models import Q

from propertylist_app.models import MessageThread


def get_or_create_canonical_thread(*, landlord, seeker, room):
    thread = (
        MessageThread.objects
        .filter(
            Q(room=room) | Q(room__isnull=True),
            landlord=landlord,
            seeker=seeker,
        )
        .order_by("id")
        .first()
    )

    if thread is None:
        thread = (
            MessageThread.objects
            .filter(Q(room=room) | Q(room__isnull=True))
            .filter(participants=landlord)
            .filter(participants=seeker)
            .distinct()
            .order_by("id")
            .first()
        )

    if thread is None:
        try:
            with transaction.atomic():
                thread = MessageThread.objects.create(
                    room=room,
                    landlord=landlord,
                    seeker=seeker,
                )
                thread.participants.set([landlord, seeker])

        except IntegrityError:
            thread = (
                MessageThread.objects
                .filter(
                    room=room,
                    landlord=landlord,
                    seeker=seeker,
                )
                .order_by("id")
                .first()
            )

            if thread is None:
                raise

    else:
        update_fields = []

        if thread.room_id is None:
            thread.room = room
            update_fields.append("room")

        if thread.landlord_id is None:
            thread.landlord = landlord
            update_fields.append("landlord")

        if thread.seeker_id is None:
            thread.seeker = seeker
            update_fields.append("seeker")

        if update_fields:
            thread.save(update_fields=update_fields)

    return thread