"""Query optimization for ordinary human-message post-save work."""

from django.db.models import Count, Exists, OuterRef, Q
from django.db.models.signals import post_save

from propertylist_app.models import (
    Message,
    MessageThread,
    MessageThreadState,
    Notification,
    UserProfile,
)
from propertylist_app.services.deep_links import build_absolute_url
from propertylist_app.services.realtime import push_user_realtime_event
from propertylist_app.signals import (
    _queue_email,
    message_created_create_notifications,
)


_INSTALLED = False


def _message_unread_counts(*, user, thread, profile):
    """Return thread/account unread totals with one aggregate query."""
    base_threads = MessageThread.objects.filter(participants=user)

    if profile.role == "landlord":
        base_threads = base_threads.filter(
            Q(landlord=user)
            | Q(
                landlord__isnull=True,
                seeker__isnull=True,
            )
        )
    else:
        base_threads = base_threads.filter(
            Q(seeker=user)
            | Q(
                landlord__isnull=True,
                seeker__isnull=True,
            )
        )

    binned_for_user = MessageThreadState.objects.filter(
        user=user,
        thread_id=OuterRef("pk"),
        in_bin=True,
    )
    base_threads = (
        base_threads
        .annotate(_message_signal_in_bin=Exists(binned_for_user))
        .filter(_message_signal_in_bin=False)
    )

    hidden_by_delete = MessageThreadState.objects.filter(
        user=user,
        thread_id=OuterRef("thread_id"),
        deleted_at__isnull=False,
        deleted_at__gte=OuterRef("created"),
    )

    counts = (
        Message.objects
        .filter(thread__in=base_threads)
        .annotate(_message_signal_hidden_by_delete=Exists(hidden_by_delete))
        .filter(_message_signal_hidden_by_delete=False)
        .filter(
            Q(metadata__system_event=True)
            | ~Q(sender=user)
        )
        .exclude(reads__user=user)
        .aggregate(
            account_unread_total=Count("id", distinct=True),
            thread_unread_count=Count(
                "id",
                filter=Q(thread_id=thread.id),
                distinct=True,
            ),
        )
    )

    return (
        counts["thread_unread_count"],
        counts["account_unread_total"],
    )


def _optimized_message_created_create_notifications(
    sender,
    instance: Message,
    created,
    **kwargs,
) -> None:
    if not created:
        return

    if instance.message_type != Message.TYPE_TEXT:
        return

    metadata = instance.metadata or {}
    if metadata.get("system_event") is True:
        return

    thread: MessageThread = instance.thread
    recipients = list(
        thread.participants
        .exclude(pk=instance.sender_id)
        .select_related("profile")
    )

    if not recipients:
        return

    MessageThreadState.objects.filter(
        user_id__in=[user.id for user in recipients],
        thread=thread,
        in_bin=True,
    ).update(in_bin=False)

    deep_link = f"/app/threads/{thread.id}"
    full_url = build_absolute_url(
        f"/messages?thread={thread.id}",
        force_login=False,
    )
    sender_name = (
        instance.sender.get_full_name()
        or instance.sender.get_username()
    )
    message_snippet = instance.body[:200] if instance.body else ""

    notifications_to_create = []
    notification_deliveries = []

    for user in recipients:
        try:
            profile = user.profile
        except UserProfile.DoesNotExist:
            profile, _ = UserProfile.objects.get_or_create(user=user)

        thread_audience = (
            Notification.Audience.LANDLORD
            if thread.landlord_id == user.id
            else (
                Notification.Audience.SEEKER
                if thread.seeker_id == user.id
                else Notification.Audience.BOTH
            )
        )
        realtime_visible = (
            thread_audience == Notification.Audience.BOTH
            or profile.role == thread_audience
        )

        if realtime_visible:
            push_user_realtime_event(
                user.id,
                "new_message",
                {
                    "message_id": instance.id,
                    "thread_id": thread.id,
                    "sender_id": instance.sender_id,
                },
            )

            thread_unread_count, account_unread_total = _message_unread_counts(
                user=user,
                thread=thread,
                profile=profile,
            )

            push_user_realtime_event(
                user.id,
                "unread_count_changed",
                {
                    "thread_id": thread.id,
                    "thread_unread_count": thread_unread_count,
                    "account_unread_total": account_unread_total,
                },
            )

        if not getattr(profile, "notify_messages", True):
            continue

        notifications_to_create.append(
            Notification(
                user=user,
                type=Notification.Type.MESSAGE,
                thread=thread,
                message=instance,
                title="New message",
                body=message_snippet,
                audience=thread_audience,
            )
        )
        notification_deliveries.append(
            (user, realtime_visible)
        )

    if notifications_to_create:
        Notification.objects.bulk_create(
            notifications_to_create,
            ignore_conflicts=True,
        )

    for user, realtime_visible in notification_deliveries:
        if realtime_visible:
            push_user_realtime_event(
                user.id,
                "new_notification",
                {
                    "kind": "message",
                    "message_id": instance.id,
                    "thread_id": thread.id,
                },
            )

        _queue_email(
            user=user,
            template_key="message.new",
            context={
                "user": {
                    "first_name": user.first_name,
                },
                "sender": {
                    "name": sender_name,
                },
                "thread_id": thread.id,
                "message_id": instance.id,
                "deep_link": deep_link,
                "cta_url": full_url,
                "thread_url": full_url,
                "snippet": message_snippet,
            },
        )


def install_message_creation_query_optimization():
    """Replace the ordinary-message signal receiver once at startup."""
    global _INSTALLED

    if _INSTALLED:
        return

    post_save.disconnect(
        receiver=message_created_create_notifications,
        sender=Message,
    )
    post_save.connect(
        receiver=_optimized_message_created_create_notifications,
        sender=Message,
        weak=False,
    )
    _INSTALLED = True
