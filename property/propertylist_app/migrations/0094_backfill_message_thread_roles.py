from django.db import migrations


def backfill_message_thread_roles(apps, schema_editor):
    MessageThread = apps.get_model(
        "propertylist_app",
        "MessageThread",
    )

    threads = (
        MessageThread.objects
        .filter(
            landlord__isnull=True,
            seeker__isnull=True,
            room__isnull=False,
        )
        .select_related("room__property_owner")
        .prefetch_related("participants")
        .iterator(chunk_size=500)
    )

    for thread in threads:
        room = thread.room
        landlord_id = getattr(room, "property_owner_id", None)

        if not landlord_id:
            continue

        participant_ids = [
            participant.id
            for participant in thread.participants.all()
        ]

        # Historical classification must be deterministic:
        # exactly two participants, one of whom is the room owner.
        if len(participant_ids) != 2:
            continue

        if landlord_id not in participant_ids:
            continue

        seeker_ids = [
            user_id
            for user_id in participant_ids
            if user_id != landlord_id
        ]

        if len(seeker_ids) != 1:
            continue

        MessageThread.objects.filter(pk=thread.pk).update(
            landlord_id=landlord_id,
            seeker_id=seeker_ids[0],
        )


class Migration(migrations.Migration):

    dependencies = [
        (
            "propertylist_app",
            "0093_messagethread_landlord_messagethread_seeker_and_more",
        ),
    ]

    operations = [
        migrations.RunPython(
            backfill_message_thread_roles,
            reverse_code=migrations.RunPython.noop,
        ),
    ]