from django.db import migrations, models
from django.db.models import Count
from django.utils import timezone


def merge_duplicate_message_threads(apps, schema_editor):
    MessageThread = apps.get_model(
        "propertylist_app",
        "MessageThread",
    )
    Message = apps.get_model(
        "propertylist_app",
        "Message",
    )
    Notification = apps.get_model(
        "propertylist_app",
        "Notification",
    )
    MessageThreadState = apps.get_model(
        "propertylist_app",
        "MessageThreadState",
    )

    duplicate_groups = (
        MessageThread.objects
        .filter(
            is_deleted=False,
            room_id__isnull=False,
            landlord_id__isnull=False,
            seeker_id__isnull=False,
        )
        .values(
            "room_id",
            "landlord_id",
            "seeker_id",
        )
        .annotate(thread_count=Count("id"))
        .filter(thread_count__gt=1)
    )

    for group in duplicate_groups.iterator():
        threads = list(
            MessageThread.objects
            .filter(
                is_deleted=False,
                room_id=group["room_id"],
                landlord_id=group["landlord_id"],
                seeker_id=group["seeker_id"],
            )
            .order_by("id")
        )

        if len(threads) < 2:
            continue

        canonical = threads[0]

        for duplicate in threads[1:]:
            # Preserve all messages by moving them to the canonical thread.
            Message.objects.filter(
                thread_id=duplicate.id,
            ).update(
                thread_id=canonical.id,
            )

            # Preserve notification/thread links.
            Notification.objects.filter(
                thread_id=duplicate.id,
            ).update(
                thread_id=canonical.id,
            )

            # Merge per-user thread state without violating the existing
            # unique (user, thread) rule.
            duplicate_states = list(
                MessageThreadState.objects.filter(
                    thread_id=duplicate.id,
                )
            )

            for duplicate_state in duplicate_states:
                canonical_state = (
                    MessageThreadState.objects
                    .filter(
                        thread_id=canonical.id,
                        user_id=duplicate_state.user_id,
                    )
                    .first()
                )

                if canonical_state is None:
                    MessageThreadState.objects.filter(
                        pk=duplicate_state.pk,
                    ).update(
                        thread_id=canonical.id,
                    )
                    continue

                # Keep whichever state was updated most recently.
                if duplicate_state.updated_at > canonical_state.updated_at:
                    MessageThreadState.objects.filter(
                        pk=canonical_state.pk,
                    ).update(
                        label=duplicate_state.label,
                        in_bin=duplicate_state.in_bin,
                        updated_at=duplicate_state.updated_at,
                    )

                MessageThreadState.objects.filter(
                    pk=duplicate_state.pk,
                ).delete()

            # If the canonical thread has no label, preserve one from a
            # duplicate thread rather than discarding it.
            if not canonical.label and duplicate.label:
                canonical.label = duplicate.label
                canonical.save(update_fields=["label"])

            # Keep the duplicate record for audit/history, but remove it
            # from the active thread set.
            MessageThread.objects.filter(
                pk=duplicate.id,
            ).update(
                is_deleted=True,
                deleted_at=timezone.now(),
            )


class Migration(migrations.Migration):

    dependencies = [
        (
            "propertylist_app",
            "0094_backfill_message_thread_roles",
        ),
    ]

    operations = [
        migrations.RunPython(
            merge_duplicate_message_threads,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="messagethread",
            constraint=models.UniqueConstraint(
                fields=("room", "landlord", "seeker"),
                condition=models.Q(
                    is_deleted=False,
                    room__isnull=False,
                    landlord__isnull=False,
                    seeker__isnull=False,
                ),
                name="uniq_active_thread_room_landlord_seeker",
            ),
        ),
    ]