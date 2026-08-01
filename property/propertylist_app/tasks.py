from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db.models import Exists, OuterRef, Q
from django.apps import apps
from django.conf import settings
from datetime import timedelta
from propertylist_app.services.tenancy_chat import post_tenancy_event

from notifications.models import NotificationTemplate, OutboundNotification
from propertylist_app.services.deep_links import build_absolute_url
from propertylist_app.models import UserProfile, Room, Review

from propertylist_app.services.tasks import (
    send_new_message_email,
    expire_paid_listings,
)
from propertylist_app.services.tenancy_dates import (
    compute_end_date,
    compute_review_window,
)


# from propertylist_app.services.reviews import update_room_rating_from_revealed_reviews

# IMPORTANT: ensure nested notification tasks are registered
# from propertylist_app.notifications.tasks import notify_completed_viewings  # noqa: F401

from django.db.models import Avg, Count

from celery import shared_task



# -------------------------------------------------------------------
# Celery decorator (safe fallback for tests)
# -------------------------------------------------------------------
try:
    from celery import shared_task
except Exception:  # pragma: no cover
    def shared_task(*args, **kwargs):
        def wrapper(fn):
            fn.delay = fn
            return fn
        return wrapper


# -------------------------------------------------------------------
# Messaging / listings
# -------------------------------------------------------------------
@shared_task(name="propertylist_app.send_new_message_email")
def task_send_new_message_email(message_id: int) -> int:
    return send_new_message_email(message_id)


@shared_task(name="propertylist_app.expire_paid_listings")
def task_expire_paid_listings() -> int:
    return expire_paid_listings()


# -------------------------------------------------------------------
# Account deletion
# -------------------------------------------------------------------
@shared_task(name="propertylist_app.delete_scheduled_accounts")
def task_delete_scheduled_accounts() -> int:
    now = timezone.now()
    UserModel = get_user_model()

    profiles = (
        UserProfile.objects
        .filter(pending_deletion_scheduled_for__isnull=False)
        .filter(pending_deletion_scheduled_for__lte=now)
        .select_related("user")
    )

    deleted = 0
    for profile in profiles:
        user = profile.user
        if not user:
            profile.pending_deletion_requested_at = None
            profile.pending_deletion_scheduled_for = None
            profile.save(
                update_fields=[
                    "pending_deletion_requested_at",
                    "pending_deletion_scheduled_for",
                ]
            )
            continue

        UserModel.objects.filter(pk=user.pk).delete()
        deleted += 1

    return deleted


# -------------------------------------------------------------------
# Nightly room rating refresh (double-blind safe)
# -------------------------------------------------------------------
@shared_task(name="propertylist_app.refresh_room_ratings_nightly")
def task_refresh_room_ratings_nightly() -> int:
    from propertylist_app.signals import _recalc_room_rating

    now = timezone.now()

    rooms = Room.objects.filter(
    Exists(
        Review.objects.filter(
            Q(tenancy__room=OuterRef("pk")) | Q(tenancy__room=OuterRef("pk")),
            role=Review.ROLE_TENANT_TO_LANDLORD,
            active=True,
            reveal_at__isnull=False,
            reveal_at__lte=now,
        )
    )
    )


    count = 0
    for room in rooms:
        _recalc_room_rating(room)
        count += 1

    return count


def _queue_email(*, user, template_key: str, context: dict | None = None) -> None:
    """
    Queue an email via notifications pipeline.
    Only queues if an active email template exists for the key.
    """
    template = NotificationTemplate.objects.filter(
        key=template_key,
        channel=NotificationTemplate.CHANNEL_EMAIL,
        is_active=True,
    ).first()
    if not template:
        return

    OutboundNotification.objects.create(
        user=user,
        channel=NotificationTemplate.CHANNEL_EMAIL,
        template_key=template_key,
        context=context or {},
    )



# -------------------------------------------------------------------
# Tenancy notifications (INBOX ONLY – stable)
# -------------------------------------------------------------------

@shared_task
def task_send_tenancy_notification(tenancy_id: int, event: str) -> int:
    Tenancy = apps.get_model("propertylist_app", "Tenancy")
    Notification = apps.get_model("propertylist_app", "Notification")
    UserProfile = apps.get_model("propertylist_app", "UserProfile")

    supported_events = {
        "proposed",
        "updated",
        "confirmed",
        "cancelled",
    }

    if event not in supported_events:
        return 0

    tenancy = (
        Tenancy.objects
        .select_related(
            "room",
            "landlord",
            "tenant",
            "proposed_by",
        )
        .filter(id=tenancy_id)
        .first()
    )

    if not tenancy:
        return 0

    room_title = getattr(tenancy.room, "title", "your room")

    # For a new proposal or counter-proposal, proposed_by is the person
    # who submitted the current tenancy terms.
    if event in {"proposed", "updated"}:
        sender = tenancy.proposed_by

    # Confirmation or cancellation is performed by the person reviewing
    # the current proposal, which is the opposite party to proposed_by.
    elif tenancy.proposed_by_id == tenancy.tenant_id:
        sender = tenancy.landlord
    else:
        sender = tenancy.tenant

    if sender is None:
        return 0

    thread, message = post_tenancy_event(
        tenancy=tenancy,
        event_type=event,
        sender=sender,
    )

    thread_deep_link = f"/app/threads/{thread.id}"
    thread_cta_url = build_absolute_url(thread_deep_link)

    def _maybe_queue(user, template_key: str):
        profile, _ = UserProfile.objects.get_or_create(user=user)

        if not getattr(profile, "notify_confirmations", True):
            return

        _queue_email(
            user=user,
            template_key=template_key,
            context={
                "user": {
                    "first_name": user.first_name,
                },
                "tenancy_id": tenancy.id,
                "thread_id": thread.id,
                "message_id": message.id,
                "room_title": room_title,
                "move_in_date": (
                    tenancy.move_in_date.isoformat()
                    if tenancy.move_in_date
                    else None
                ),
                "duration_months": tenancy.duration_months,
                "monthly_rent": (
                    str(tenancy.room.price_per_month)
                    if tenancy.room.price_per_month is not None
                    else None
                ),
                "deep_link": thread_deep_link,
                "cta_url": thread_cta_url,
            },
        )

    def _create_notification(
        *,
        user,
        notification_type: str,
        title: str,
        body: str,
    ):
        Notification.objects.get_or_create(
            user=user,
            type=notification_type,
            target_type="message",
            target_id=message.id,
            defaults={
                "thread": thread,
                "message": message,
                "title": title,
                "body": body,
            },
        )

    if event == "proposed":
        target_user = (
            tenancy.landlord
            if sender.id == tenancy.tenant_id
            else tenancy.tenant
        )

        _create_notification(
            user=target_user,
            notification_type="tenancy_proposed",
            title="Tenancy proposal",
            body=(
                f"A tenancy proposal was created for: "
                f"{room_title}. Please respond."
            ),
        )

        _maybe_queue(
            target_user,
            "tenancy.proposed",
        )

        return 1

    if event == "confirmed":
        for user in (tenancy.landlord, tenancy.tenant):
            _create_notification(
                user=user,
                notification_type="tenancy_confirmed",
                title="Tenancy confirmed",
                body=f"Tenancy confirmed for: {room_title}.",
            )

            _maybe_queue(
                user,
                "tenancy.confirmed",
            )

        return 2

    if event == "cancelled":
        for user in (tenancy.landlord, tenancy.tenant):
            _create_notification(
                user=user,
                notification_type="tenancy_cancelled",
                title="Tenancy cancelled",
                body=f"Tenancy cancelled for: {room_title}.",
            )

            _maybe_queue(
                user,
                "tenancy.cancelled",
            )

        return 2

    # updated
    target_user = (
        tenancy.landlord
        if sender.id == tenancy.tenant_id
        else tenancy.tenant
    )

    _create_notification(
        user=target_user,
        notification_type="tenancy_updated",
        title="Tenancy updated",
        body=f"Tenancy proposal updated for: {room_title}.",
    )

    _maybe_queue(
        target_user,
        "tenancy.updated",
    )

    return 1


def _refresh_user_ratings_for_user_ids(user_ids):
    Review = apps.get_model("propertylist_app", "Review")
    UserProfile = apps.get_model("propertylist_app", "UserProfile")

    now = timezone.now()

    for user_id in user_ids:
        tenant_agg = Review.objects.filter(
            role=Review.ROLE_LANDLORD_TO_TENANT,
            reviewee_id=user_id,
            active=True,
            reveal_at__isnull=False,
            reveal_at__lte=now,
            submitted_at__isnull=False,
        ).aggregate(avg=Avg("overall_rating"), cnt=Count("id"))

        landlord_agg = Review.objects.filter(
            role=Review.ROLE_TENANT_TO_LANDLORD,
            reviewee_id=user_id,
            active=True,
            reveal_at__isnull=False,
            reveal_at__lte=now,
            submitted_at__isnull=False,
        ).aggregate(avg=Avg("overall_rating"), cnt=Count("id"))

        UserProfile.objects.filter(user_id=user_id).update(
            avg_tenant_rating=float(tenant_agg["avg"] or 0.0),
            number_tenant_ratings=int(tenant_agg["cnt"] or 0),
            avg_landlord_rating=float(landlord_agg["avg"] or 0.0),
            number_landlord_ratings=int(landlord_agg["cnt"] or 0),
        )






# -------------------------------------------------------------------
# Tenancy prompts sweep (still-living + reviews)
# -------------------------------------------------------------------

@shared_task
def task_tenancy_prompts_sweep() -> int:
    Tenancy = apps.get_model("propertylist_app", "Tenancy")
    Notification = apps.get_model("propertylist_app", "Notification")
    Review = apps.get_model("propertylist_app", "Review")
    Room = apps.get_model("propertylist_app", "Room")

    now = timezone.now()
    
    UserProfile = apps.get_model("propertylist_app", "UserProfile")
    
    Message = apps.get_model("propertylist_app", "Message")

    def _tenancy_thread_deep_link(tenancy):
        """
        Return the existing inbox thread created for this tenancy.

        Tenancy proposal, update and confirmation messages store the
        tenancy ID inside Message.metadata.
        """
        tenancy_message = (
            Message.objects
            .select_related("thread")
            .filter(metadata__tenancy_id=tenancy.id)
            .order_by("-created")
            .first()
        )

        if tenancy_message and tenancy_message.thread_id:
            return f"/app/threads/{tenancy_message.thread_id}"

        # Safe fallback for older tenancy records that may not yet have
        # an inbox-thread message.
        return f"/app/tenancies/{tenancy.id}"
    
    
    
    def _post_tenancy_prompt_message(
        tenancy,
        *,
        event_type: str,
        body: str,
        available_action: str,
    ):
        """
        Add one system-style tenancy prompt to the existing tenancy
        conversation.

        The event key prevents Celery retries and repeated sweeps from
        creating duplicate thread messages.
        """
        tenancy_message = (
            Message.objects
            .select_related("thread")
            .filter(metadata__tenancy_id=tenancy.id)
            .order_by("-created")
            .first()
        )

        if not tenancy_message or not tenancy_message.thread_id:
            return None, None

        event_key = f"tenancy:{tenancy.id}:{event_type}"

        existing_message = (
            Message.objects
            .select_related("thread")
            .filter(metadata__event_key=event_key)
            .first()
        )

        if existing_message:
            return existing_message.thread, existing_message

        sender = tenancy.proposed_by

        if sender is None or sender.id not in {
            tenancy.landlord_id,
            tenancy.tenant_id,
        }:
            sender = tenancy.landlord

        message = Message.objects.create(
            thread=tenancy_message.thread,
            sender=sender,
            body=body,
            message_type=Message.TYPE_TEXT,
            metadata={
                "tenancy_id": tenancy.id,
                "room_id": tenancy.room_id,
                "room_title": tenancy.room.title,
                "event_type": event_type,
                "event_key": event_key,
                "system_event": True,
                "available_actions": [available_action],
            },
        )

        return tenancy_message.thread, message
    
    
    
    
    

    def _maybe_queue_reminder(user, template_key: str, *, deep_link: str, room_title: str):
        profile, _ = UserProfile.objects.get_or_create(user=user)
        if not getattr(profile, "notify_reminders", True):
            return
        _queue_email(
            user=user,
            template_key=template_key,
            context={
                "user": {"first_name": user.first_name},
                "room_title": room_title,
                "deep_link": deep_link,
                "cta_url": build_absolute_url(deep_link),
            },
        )
    
    
    count = 0
    
        # -------------------------------------------------
    # 1) tenancy ending reminder
    # -------------------------------------------------
    due_checks = (
        Tenancy.objects
        .select_related("room", "landlord", "tenant")
        .filter(
            status__in=[
                Tenancy.STATUS_CONFIRMED,
                Tenancy.STATUS_ACTIVE,
            ],
            still_living_check_at__isnull=False,
            still_living_check_at__lte=now,
            still_living_confirmed_at__isnull=True,
        )
    )

    for tenancy in due_checks:
        landlord_done = bool(
            getattr(
                tenancy,
                "still_living_landlord_confirmed_at",
                None,
            )
        )
        tenant_done = bool(
            getattr(
                tenancy,
                "still_living_tenant_confirmed_at",
                None,
            )
        )

        # Both parties have completed the check.
        if landlord_done and tenant_done:
            tenancy.still_living_confirmed_at = now
            tenancy.save(
                update_fields=["still_living_confirmed_at"]
            )
            continue

        deep_link = _tenancy_thread_deep_link(tenancy)

        title = "Your tenancy is ending soon"
        body = (
            f"Your tenancy for {tenancy.room.title} is due to end soon. "
            "Update the tenancy information if you are continuing. "
            "If you are moving out, no action is required."
        )
        
        prompt_thread, prompt_message = _post_tenancy_prompt_message(
            tenancy,
            event_type="still_living_check",
            body=(
                "Your tenancy is ending soon.\n\n"
                "If the tenancy is continuing, update the tenancy "
                "information. If you are moving out, no action is required."
            ),
            available_action="update_tenancy",
        )

        if prompt_thread is not None:
            deep_link = f"/app/threads/{prompt_thread.id}"
        
        

        def _notify_user(user, template_key):
            reminder_exists = Notification.objects.filter(
                user=user,
                type="tenancy_still_living_check",
                target_type="still_living_check",
                target_id=tenancy.id,
            ).exists()

            if reminder_exists:
                return 0

            Notification.objects.create(
                user=user,
                type="tenancy_still_living_check",
                target_type="still_living_check",
                target_id=tenancy.id,
                thread=prompt_thread,
                message=prompt_message,
                title=title,
                body=body,
            )

            _maybe_queue_reminder(
                user,
                template_key,
                deep_link=deep_link,
                room_title=tenancy.room.title,
            )

            return 1

        landlord_notification_created = 0
        tenant_notification_created = 0

        if not landlord_done:
            landlord_notification_created = _notify_user(
                tenancy.landlord,
                "tenancy.still_living_check_landlord",
            )
            count += landlord_notification_created

        if not tenant_done:
            tenant_notification_created = _notify_user(
                tenancy.tenant,
                "tenancy.still_living_check",
            )
            count += tenant_notification_created

        # TEMPORARY QA RULE:
        # When neither party has updated the tenancy information,
        # open the review window 10 minutes after the ending reminder
        # is first created. Production must revert to end date + 7 days.
        reminder_created = bool(
            landlord_notification_created
            or tenant_notification_created
        )

        if (
            not landlord_done
            and not tenant_done
            and reminder_created
        ):
            tenancy.review_open_at = now + timedelta(minutes=10)
            tenancy.review_deadline_at = (
                tenancy.review_open_at + timedelta(days=30)
            )
            tenancy.save(
                update_fields=[
                    "review_open_at",
                    "review_deadline_at",
                ]
            )
            
            
            
    # -------------------------------------------------
    # 2) reviews open -> notifications (if any side missing)
    # -------------------------------------------------
    
    due_reviews = Tenancy.objects.filter(
        status=Tenancy.STATUS_ENDED,
        review_open_at__isnull=False,
        review_open_at__lte=now,
    )
    
    for t in due_reviews:
        tenant_done = Review.objects.filter(
            tenancy=t,
            role=Review.ROLE_TENANT_TO_LANDLORD,
        ).exists()

        landlord_done = Review.objects.filter(
            tenancy=t,
            role=Review.ROLE_LANDLORD_TO_TENANT,
        ).exists()

        # Both parties have already reviewed.
        if tenant_done and landlord_done:
            continue

        # Add one review-available message to the existing tenancy thread.
        # Repeated Celery runs reuse the same message.
        prompt_thread, prompt_message = _post_tenancy_prompt_message(
            t,
            event_type="review_available",
            body=(
                "Your review window is now open.\n\n"
                "You can now leave a review for this tenancy."
            ),
            available_action="leave_review",
        )

        # Email and in-app notification should open the exact tenancy thread.
        # Older tenancies without a thread use the safe fallback.
        review_deep_link = (
            f"/app/threads/{prompt_thread.id}"
            if prompt_thread is not None
            else _tenancy_thread_deep_link(t)
        )

        # Notify the landlord only if the landlord has not reviewed.
        if not landlord_done:
            _, notification_created = Notification.objects.get_or_create(
                user=t.landlord,
                type="review_available",
                target_type="tenancy_review",
                target_id=t.id,
                defaults={
                    "thread": prompt_thread,
                    "message": prompt_message,
                    "title": "Review available",
                    "body": (
                        f"You can now leave a review for "
                        f"{t.room.title}."
                    ),
                },
            )

            if notification_created:
                _maybe_queue_reminder(
                    t.landlord,
                    "tenancy.review_available",
                    deep_link=review_deep_link,
                    room_title=t.room.title,
                )
                count += 1

        # Notify the tenant only if the tenant has not reviewed.
        if not tenant_done:
            _, notification_created = Notification.objects.get_or_create(
                user=t.tenant,
                type="review_available",
                target_type="tenancy_review",
                target_id=t.id,
                defaults={
                    "thread": prompt_thread,
                    "message": prompt_message,
                    "title": "Review available",
                    "body": (
                        f"You can now leave a review for "
                        f"{t.room.title}."
                    ),
                },
            )

            if notification_created:
                _maybe_queue_reminder(
                    t.tenant,
                    "tenancy.review_available",
                    deep_link=review_deep_link,
                    room_title=t.room.title,
                )
                count += 1
    # -------------------------------------------------
    # 3) REVEAL + RATING UPDATE (your schema)
    #
    # Review is visible when:
    # - active == True
    # - reveal_at <= now
    #
    # Rating should be calculated from ONLY revealed reviews (active=True).
    # -------------------------------------------------

    # 3a) Reveal any reviews whose reveal time has passed
    to_reveal = Review.objects.filter(
        active=False,
        reveal_at__isnull=False,
        reveal_at__lte=now,
    )

    revealed_count = to_reveal.update(active=True)
    if revealed_count:
        # refresh tenant ratings for tenants affected by newly revealed landlord->tenant reviews
        affected_tenant_ids = (
            Review.objects.filter(
                active=True,
                reveal_at__isnull=False,
                reveal_at__lte=now,
                role=Review.ROLE_LANDLORD_TO_TENANT,
            )
            .values_list("reviewee_id", flat=True)
            .distinct()
        )

        affected_user_ids = (
            Review.objects.filter(
                active=True,
                reveal_at__isnull=False,
                reveal_at__lte=now,
            )
            .values_list("reviewee_id", flat=True)
            .distinct()
        )

        _refresh_user_ratings_for_user_ids(affected_user_ids)



    # 3b) Recalculate ratings for rooms affected by reveal
    if revealed_count:
        # rooms impacted by newly revealed reviews
        room_ids = (
            Review.objects.filter(active=True, reveal_at__lte=now)
            .exclude(tenancy__room_id__isnull=True)
            .values_list("tenancy__room_id", flat=True)
            .distinct()
        )

        for room_id in room_ids:
            agg = Review.objects.filter(
                tenancy__room_id=room_id,
                role=Review.ROLE_TENANT_TO_LANDLORD,  # only tenant -> landlord affects room rating
                active=True,
                reveal_at__isnull=False,
                reveal_at__lte=now,
            ).aggregate(
                avg=Avg("overall_rating"),
                cnt=Count("id"),
            )

            avg_val = float(agg["avg"] or 0.0)
            cnt_val = int(agg["cnt"] or 0)

            Room.objects.filter(id=room_id).update(
                avg_rating=avg_val,
                number_rating=cnt_val,
            )

    return count

# -------------------------------------------------------------------
# Tenancy lifecycle + automatic review window
# -------------------------------------------------------------------


@shared_task
def task_refresh_tenancy_status_and_review_windows():
    Tenancy = apps.get_model("propertylist_app", "Tenancy")

    today = timezone.localdate()

    for t in Tenancy.objects.exclude(status=Tenancy.STATUS_CANCELLED).iterator():
        if t.status == Tenancy.STATUS_CONFIRMED and t.move_in_date <= today:
            t.status = Tenancy.STATUS_ACTIVE

        end_date = compute_end_date(t.move_in_date, t.duration_months)

        if t.status in (Tenancy.STATUS_CONFIRMED, Tenancy.STATUS_ACTIVE) and end_date < today:
            t.status = Tenancy.STATUS_ENDED

        if (
            t.review_open_at is None
            or t.review_deadline_at is None
            or t.still_living_check_at is None
        ):
            ro, rd, sl = compute_review_window(
                t.move_in_date,
                t.duration_months,
            )
            t.review_open_at = t.review_open_at or ro
            t.review_deadline_at = t.review_deadline_at or rd
            t.still_living_check_at = t.still_living_check_at or sl

        t.save()
